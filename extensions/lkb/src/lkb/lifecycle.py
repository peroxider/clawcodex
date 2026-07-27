"""Crash-recoverable Board lifecycle, immutable archives, purge, and GC."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .atomic_file import atomic_write_json
from .commands import CommandResult
from .ir_hash import canonical_hash
from .json_store import BoardEnvelope, JsonBoardStore, validate_board_envelope

VALID_STATES = ("active", "closed", "archiving", "archived", "trashed", "purging")
_TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"closed"}),
    "closed": frozenset({"active", "archiving", "trashed"}),
    "archiving": frozenset({"archived", "closed"}),
    "archived": frozenset({"active", "trashed"}),
    "trashed": frozenset({"active", "purging"}),
    "purging": frozenset({"trashed"}),
}

GC_TEMP_AGE_SECONDS = 24 * 3600
GC_SESSION_ORPHAN_AGE_SECONDS = 7 * 24 * 3600
GC_QUARANTINE_AGE_SECONDS = 30 * 24 * 3600
GC_TOMBSTONE_AGE_SECONDS = 90 * 24 * 3600

__all__ = [
    "GC_QUARANTINE_AGE_SECONDS",
    "GC_SESSION_ORPHAN_AGE_SECONDS",
    "GC_TEMP_AGE_SECONDS",
    "GC_TOMBSTONE_AGE_SECONDS",
    "GcCandidate",
    "LifecycleData",
    "LifecycleError",
    "LifecycleTransitionDenied",
    "VALID_STATES",
    "archive_board",
    "board_lifecycle_state",
    "close_board",
    "gc_apply",
    "gc_scan",
    "genesis_lifecycle",
    "ordinary_write_allowed",
    "ordinary_write_denial_reason",
    "purge_board",
    "read_archive",
    "read_tombstone",
    "reopen_board",
    "restore_board",
    "tombstone_path",
    "transition",
    "trash_board",
]


class LifecycleError(Exception):
    """Base error for lifecycle protocols."""


class LifecycleTransitionDenied(LifecycleError):
    def __init__(self, board_id: str, from_state: str, to_state: str, reason: str) -> None:
        self.board_id = board_id
        self.from_state = from_state
        self.to_state = to_state
        self.transition_reason = reason
        super().__init__(
            f"Lifecycle transition denied for board {board_id!r}: "
            f"{from_state} -> {to_state} ({reason})"
        )


@dataclass
class LifecycleData:
    state: str = "active"
    scope: str = "project"
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""
    archived_at: str = ""
    retention_policy: str = "default"
    origin_project_uri: str = ""

    def __post_init__(self) -> None:
        if self.state not in VALID_STATES:
            raise ValueError(f"invalid lifecycle state: {self.state!r}")
        if self.scope not in {"project", "session"}:
            raise ValueError(f"invalid lifecycle scope: {self.scope!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "archived_at": self.archived_at,
            "retention_policy": self.retention_policy,
            "origin_project_uri": self.origin_project_uri,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LifecycleData:
        return cls(
            state=str(value.get("state", "active")),
            scope=str(value.get("scope", "project")),
            created_at=str(value.get("created_at", "")),
            updated_at=str(value.get("updated_at", "")),
            closed_at=str(value.get("closed_at", "")),
            archived_at=str(value.get("archived_at", "")),
            retention_policy=str(value.get("retention_policy", "default")),
            origin_project_uri=str(value.get("origin_project_uri", "")),
        )


def genesis_lifecycle(
    *,
    scope: str,
    created_at: str,
    origin_project_uri: str,
    retention_policy: str = "default",
) -> dict[str, Any]:
    return LifecycleData(
        scope=scope,
        created_at=created_at,
        updated_at=created_at,
        retention_policy=retention_policy,
        origin_project_uri=origin_project_uri,
    ).to_dict()


def board_lifecycle_state(envelope: BoardEnvelope) -> str:
    return str((envelope.lifecycle or {}).get("state", "active"))


def ordinary_write_denial_reason(envelope: BoardEnvelope) -> str | None:
    state = board_lifecycle_state(envelope)
    if state == "active":
        return None
    if state in {"closed", "archived", "trashed"}:
        return f"board is {state}; ordinary writes are disabled"
    if state in {"archiving", "purging"}:
        return f"board lifecycle transition is in progress ({state})"
    return f"unknown lifecycle state {state!r}; refusing write"


def ordinary_write_allowed(envelope: BoardEnvelope) -> bool:
    return ordinary_write_denial_reason(envelope) is None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_active_claims(envelope: BoardEnvelope) -> bool:
    return any(claim.get("status") == "active" for claim in envelope.claims.values())


def transition(
    envelope: BoardEnvelope,
    to_state: str,
    *,
    actor: str,
    reason: str | None = None,
    override_active_claims: bool = False,
) -> BoardEnvelope:
    """Pure state transition; persistence is owned by the caller."""
    from_state = board_lifecycle_state(envelope)
    if to_state not in VALID_STATES:
        raise LifecycleTransitionDenied(
            envelope.board_id(), from_state, to_state, f"invalid target state {to_state!r}"
        )
    if from_state == to_state:
        return envelope
    if to_state not in _TRANSITIONS.get(from_state, frozenset()):
        raise LifecycleTransitionDenied(
            envelope.board_id(), from_state, to_state, "transition is not allowed"
        )
    if to_state in {"closed", "archiving", "purging"} and _has_active_claims(envelope):
        if not override_active_claims or not reason:
            raise LifecycleTransitionDenied(
                envelope.board_id(),
                from_state,
                to_state,
                "active claims require an authorized override and non-empty reason",
            )

    result = envelope.clone()
    lifecycle = LifecycleData.from_dict(result.lifecycle)
    now = _now_iso()
    lifecycle.state = to_state
    lifecycle.updated_at = now
    if to_state == "closed":
        lifecycle.closed_at = now
    elif to_state == "archived":
        lifecycle.archived_at = now
    elif to_state == "active":
        lifecycle.closed_at = ""
        lifecycle.archived_at = ""
    extras = {
        key: copy.deepcopy(value)
        for key, value in result.lifecycle.items()
        if key not in lifecycle.to_dict()
    }
    result.lifecycle = lifecycle.to_dict()
    result.lifecycle.update(extras)
    event: dict[str, Any] = {
        "type": "lifecycle_transition",
        "from_state": from_state,
        "to_state": to_state,
        "actor": actor,
        "timestamp": now,
    }
    if reason:
        event["reason"] = reason
    if override_active_claims:
        event["override_active_claims"] = True
    result.events.append(event)
    return result


def _execute_lifecycle(
    store: JsonBoardStore,
    board_id: str,
    command_id: str,
    request_hash: str,
    mutate: Callable[[BoardEnvelope], tuple[BoardEnvelope, CommandResult]],
    *,
    actor: str,
    reason: str | None,
) -> CommandResult:
    return store.execute_atomic(
        board_id,
        command_id,
        request_hash,
        None,
        mutate,
        actor=actor,
        reason=reason,
        lifecycle_operation=True,
    )


def _simple_mutator(
    state: str,
    *,
    actor: str,
    command_id: str,
    reason: str | None,
    override_active_claims: bool = False,
) -> Callable[[BoardEnvelope], tuple[BoardEnvelope, CommandResult]]:
    def mutate(envelope: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
        candidate = transition(
            envelope,
            state,
            actor=actor,
            reason=reason,
            override_active_claims=override_active_claims,
        )
        return candidate, CommandResult(
            decision="committed", command_id=command_id, reason=reason
        )

    return mutate


def close_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str | None = None,
    override_active_claims: bool = False,
) -> CommandResult:
    return _execute_lifecycle(
        store,
        board_id,
        command_id,
        request_hash,
        _simple_mutator(
            "closed",
            actor=actor,
            command_id=command_id,
            reason=reason,
            override_active_claims=override_active_claims,
        ),
        actor=actor,
        reason=reason,
    )


def reopen_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str | None = None,
) -> CommandResult:
    return _execute_lifecycle(
        store,
        board_id,
        command_id,
        request_hash,
        _simple_mutator(
            "active", actor=actor, command_id=command_id, reason=reason
        ),
        actor=actor,
        reason=reason,
    )


def trash_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str | None = None,
) -> CommandResult:
    return _execute_lifecycle(
        store,
        board_id,
        command_id,
        request_hash,
        _simple_mutator(
            "trashed", actor=actor, command_id=command_id, reason=reason
        ),
        actor=actor,
        reason=reason,
    )


def _verify_envelope_hash(data: dict[str, Any]) -> bool:
    integrity = data.get("integrity")
    if not isinstance(integrity, dict) or not integrity.get("payloadHash"):
        return False
    payload = {key: value for key, value in data.items() if key != "integrity"}
    return canonical_hash(payload) == integrity["payloadHash"]


def read_archive(path: Path | str, *, expected_board_id: str) -> dict[str, Any]:
    """Read one immutable ``lkb-archive-v1`` wrapper and verify all links."""
    archive_path = Path(path)
    try:
        data = json.loads(archive_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"archive is unreadable: {archive_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("archiveFormat") != "lkb-archive-v1":
        raise LifecycleError("unsupported archive format")
    if data.get("schemaVersion") != 1:
        raise LifecycleError(f"unsupported archive schema {data.get('schemaVersion')!r}")
    if data.get("boardId") != expected_board_id:
        raise LifecycleError("archive Board ID mismatch")
    expected_hash = data.get("payloadHash")
    payload = {key: value for key, value in data.items() if key != "payloadHash"}
    if not expected_hash or canonical_hash(payload) != expected_hash:
        raise LifecycleError("archive payload hash mismatch")
    envelope = data.get("envelope")
    if not isinstance(envelope, dict) or not _verify_envelope_hash(envelope):
        raise LifecycleError("archive envelope hash mismatch")
    if envelope.get("board", {}).get("board_id") != expected_board_id:
        raise LifecycleError("archive envelope Board ID mismatch")
    if envelope.get("storeRevision") != data.get("sourceStoreRevision"):
        raise LifecycleError("archive source revision mismatch")
    if envelope.get("integrity", {}).get("payloadHash") != data.get("sourcePayloadHash"):
        raise LifecycleError("archive source payload hash mismatch")
    try:
        validate_board_envelope(envelope, board_id=expected_board_id, verify_hash=True)
    except Exception as exc:
        raise LifecycleError(f"archive envelope is invalid: {exc}") from exc
    return data


def _hit(store: JsonBoardStore, name: str) -> None:
    failpoint = getattr(store, "_failpoint", None)
    if failpoint is not None:
        failpoint.hit(name)


def _archive_path(
    store: JsonBoardStore, board_id: str, source: BoardEnvelope, operation_id: str
) -> Path:
    from .board_resolver import safe_board_id

    board_dir = Path(getattr(store, "_board_dir"))
    digest = str(source.integrity["payloadHash"]).split(":", 1)[-1][:16]
    filename = f"r{source.store_revision:020d}-{digest}-{operation_id}.json"
    return board_dir.parent.parent / "archives" / safe_board_id(board_id) / filename


def _publish_archive(
    store: JsonBoardStore,
    board_id: str,
    source: BoardEnvelope,
    operation_id: str,
    *,
    actor: str,
    reason: str | None,
    created_at: str,
) -> tuple[Path, str]:
    source_data = source.to_dict()
    if not _verify_envelope_hash(source_data):
        raise LifecycleError("source envelope hash is invalid")
    path = _archive_path(store, board_id, source, operation_id)
    document: dict[str, Any] = {
        "archiveFormat": "lkb-archive-v1",
        "schemaVersion": source.schema_version,
        "boardId": board_id,
        "sourceStoreRevision": source.store_revision,
        "sourcePayloadHash": source.integrity["payloadHash"],
        "archiveId": operation_id,
        "createdAt": created_at,
        "createdBy": actor,
        "reason": reason or "",
        "envelope": source_data,
    }
    archive_hash = canonical_hash(document)
    document["payloadHash"] = archive_hash
    root = _lkb_root_for_store(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_chain(root, path.parent) or (
        path.exists() and not _safe_chain(root, path)
    ):
        raise LifecycleError(f"unsafe archive publication path: {path}")
    if path.exists():
        existing = read_archive(path, expected_board_id=board_id)
        if existing.get("payloadHash") != archive_hash:
            raise LifecycleError("immutable archive path already contains different content")
        return path, archive_hash
    _hit(store, "archive_before_publish")
    atomic_write_json(
        path,
        document,
        fsync_dir=True,
        failpoint=getattr(store, "_failpoint", None),
        payload_hash_key="payloadHash",
    )
    read_archive(path, expected_board_id=board_id)
    _hit(store, "archive_after_publish")
    return path, archive_hash


def archive_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str | None = None,
) -> CommandResult:
    """Persist ``archiving``, publish an immutable snapshot, then CAS archived."""
    current = store.load()
    state = board_lifecycle_state(current)
    if state == "archived":
        info = current.lifecycle.get("archive_info")
        if not isinstance(info, dict):
            raise LifecycleError("archived board has no archive provenance")
        archive = read_archive(Path(str(info["archive_path"])), expected_board_id=board_id)
        if archive["payloadHash"] != info.get("archive_hash"):
            raise LifecycleError("archived board provenance hash mismatch")
        return CommandResult(
            decision="committed",
            command_id=command_id,
            reason=str(info.get("reason", reason or "")),
        )
    if state not in {"closed", "archiving"}:
        raise LifecycleTransitionDenied(board_id, state, "archiving", "board must be closed")

    if state == "closed":
        operation_id = uuid.uuid4().hex

        def prepare(envelope: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
            candidate = transition(envelope, "archiving", actor=actor, reason=reason)
            candidate.lifecycle["archive_operation"] = {
                "archive_id": operation_id,
                "actor": actor,
                "reason": reason or "",
                "started_at": _now_iso(),
            }
            return candidate, CommandResult(
                decision="committed", command_id=f"{command_id}:prepare", reason=reason
            )

        _execute_lifecycle(
            store,
            board_id,
            f"{command_id}:prepare",
            f"{request_hash}:prepare",
            prepare,
            actor=actor,
            reason=reason,
        )
        _hit(store, "archive_after_prepare")

    source = store.load()
    if board_lifecycle_state(source) != "archiving" or _has_active_claims(source):
        raise LifecycleTransitionDenied(
            board_id, board_lifecycle_state(source), "archived", "archive is not quiescent"
        )
    operation = source.lifecycle.get("archive_operation")
    if not isinstance(operation, dict) or not operation.get("archive_id"):
        raise LifecycleError("archiving board has no resumable archive operation")
    operation_id = str(operation["archive_id"])
    operation_actor = str(operation.get("actor", actor))
    operation_reason = str(operation.get("reason", reason or ""))
    archive_path, archive_hash = _publish_archive(
        store,
        board_id,
        source,
        operation_id,
        actor=operation_actor,
        reason=operation_reason,
        created_at=str(operation.get("started_at", "")),
    )
    source_revision = source.store_revision
    source_hash = str(source.integrity["payloadHash"])

    def commit(envelope: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
        actual_operation = envelope.lifecycle.get("archive_operation")
        if (
            board_lifecycle_state(envelope) != "archiving"
            or envelope.store_revision != source_revision
            or envelope.integrity.get("payloadHash") != source_hash
            or not isinstance(actual_operation, dict)
            or actual_operation.get("archive_id") != operation_id
        ):
            raise LifecycleError("archive CAS failed; verified immutable archive retained")
        candidate = transition(
            envelope, "archived", actor=operation_actor, reason=operation_reason
        )
        candidate.lifecycle.pop("archive_operation", None)
        candidate.lifecycle["archive_info"] = {
            "archive_id": operation_id,
            "archive_path": str(archive_path),
            "archive_hash": archive_hash,
            "source_store_revision": source_revision,
            "source_payload_hash": source_hash,
            "archived_by": operation_actor,
            "archived_at": candidate.lifecycle["archived_at"],
            "reason": operation_reason,
        }
        return candidate, CommandResult(
            decision="committed", command_id=command_id, reason=operation_reason
        )

    return _execute_lifecycle(
        store,
        board_id,
        f"{command_id}:commit",
        f"{request_hash}:commit:{archive_hash}",
        commit,
        actor=operation_actor,
        reason=operation_reason,
    )


def _archive_ref_values(archive_ref: Any) -> tuple[str, Path, int, str]:
    try:
        return (
            str(archive_ref.board_id),
            Path(archive_ref.archive_path),
            int(archive_ref.store_revision),
            str(archive_ref.payload_hash),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise LifecycleError("restore requires a valid ArchiveRef") from exc


def restore_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    archive_ref: Any,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str | None = None,
) -> CommandResult:
    """Restore the explicitly selected immutable ArchiveRef into this Board."""
    ref_board_id, path, ref_revision, ref_hash = _archive_ref_values(archive_ref)
    if ref_board_id != board_id:
        raise LifecycleError("ArchiveRef Board ID mismatch")
    archive = read_archive(path, expected_board_id=board_id)
    if ref_revision and ref_revision != int(archive["sourceStoreRevision"]):
        raise LifecycleError("ArchiveRef revision mismatch")
    if ref_hash and ref_hash != str(archive["payloadHash"]):
        raise LifecycleError("ArchiveRef payload hash mismatch")
    source = BoardEnvelope.from_dict(archive["envelope"])

    def mutate(envelope: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
        state = board_lifecycle_state(envelope)
        if state not in {"archived", "trashed", "closed"}:
            raise LifecycleTransitionDenied(board_id, state, "active", "restore target is not idle")
        candidate = transition(envelope, "active", actor=actor, reason=reason)
        for name in (
            "graphs",
            "nodes",
            "edges",
            "claims",
            "assertions",
            "evidence",
            "validation_runs",
            "history_segments",
        ):
            setattr(candidate, name, copy.deepcopy(getattr(source, name)))
        candidate.lifecycle["restore_info"] = {
            "source_archive_id": archive["archiveId"],
            "source_archive_hash": archive["payloadHash"],
            "source_store_revision": archive["sourceStoreRevision"],
            "source_archive_path": str(path),
            "restored_by": actor,
            "restored_at": _now_iso(),
        }
        return candidate, CommandResult(
            decision="committed", command_id=command_id, reason=reason
        )

    return _execute_lifecycle(
        store,
        board_id,
        command_id,
        request_hash,
        mutate,
        actor=actor,
        reason=reason,
    )


def _lkb_root_for_store(store: JsonBoardStore) -> Path:
    return Path(getattr(store, "_board_dir")).parent.parent


def tombstone_path(root: Path | str, board_id: str) -> Path:
    from .board_resolver import safe_board_id

    return Path(root) / "tombstones" / f"{safe_board_id(board_id)}.json"


def read_tombstone(path: Path | str, *, expected_board_id: str) -> dict[str, Any]:
    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"tombstone is unreadable: {target}: {exc}") from exc
    if not isinstance(data, dict) or data.get("tombstoneFormat") != "lkb-tombstone-v1":
        raise LifecycleError("unsupported tombstone format")
    if data.get("schemaVersion") != 1:
        raise LifecycleError(f"unsupported tombstone schema {data.get('schemaVersion')!r}")
    if data.get("boardId") != expected_board_id:
        raise LifecycleError("tombstone Board ID mismatch")
    expected = data.get("payloadHash")
    payload = {key: value for key, value in data.items() if key != "payloadHash"}
    if not expected or canonical_hash(payload) != expected:
        raise LifecycleError("tombstone payload hash mismatch")
    return data


def _tombstone_document(
    board_id: str,
    purging: BoardEnvelope,
    operation_id: str,
    *,
    actor: str,
    reason: str,
    purged_at: str,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "tombstoneFormat": "lkb-tombstone-v1",
        "schemaVersion": 1,
        "boardId": board_id,
        "purgeId": operation_id,
        "sourceStoreRevision": purging.store_revision,
        "sourcePayloadHash": purging.integrity["payloadHash"],
        "purgedBy": actor,
        "purgedAt": purged_at,
        "reason": reason,
    }
    document["payloadHash"] = canonical_hash(document)
    return document


def _purge_pending_path(root: Path, board_id: str) -> Path:
    from .board_resolver import safe_board_id

    return root / "tombstones" / f".{safe_board_id(board_id)}.purge-pending"


def _read_purge_pending(path: Path, *, expected_board_id: str) -> dict[str, Any]:
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError(f"purge journal is unreadable: {path}: {exc}") from exc
    if (
        not isinstance(pending, dict)
        or pending.get("pendingFormat") != "lkb-purge-pending-v1"
        or pending.get("boardId") != expected_board_id
    ):
        raise LifecycleError("invalid purge journal")
    expected = pending.get("payloadHash")
    payload = {key: value for key, value in pending.items() if key != "payloadHash"}
    if not expected or canonical_hash(payload) != expected:
        raise LifecycleError("purge journal payload hash mismatch")
    tombstone = pending.get("tombstone")
    if not isinstance(tombstone, dict):
        raise LifecycleError("purge journal has no tombstone candidate")
    tombstone_payload = {
        key: value for key, value in tombstone.items() if key != "payloadHash"
    }
    if (
        tombstone.get("boardId") != expected_board_id
        or tombstone.get("tombstoneFormat") != "lkb-tombstone-v1"
        or canonical_hash(tombstone_payload) != tombstone.get("payloadHash")
    ):
        raise LifecycleError("purge journal tombstone candidate is invalid")
    return pending


def _write_purge_pending(
    store: JsonBoardStore,
    board_id: str,
    tombstone: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    root = _lkb_root_for_store(store)
    path = _purge_pending_path(root, board_id)
    pending: dict[str, Any] = {
        "pendingFormat": "lkb-purge-pending-v1",
        "schemaVersion": 1,
        "boardId": board_id,
        "purgeId": tombstone["purgeId"],
        "tombstone": tombstone,
    }
    pending["payloadHash"] = canonical_hash(pending)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_chain(root, path.parent) or (
        path.exists() and not _safe_chain(root, path)
    ):
        raise LifecycleError(f"unsafe purge journal path: {path}")
    if path.exists():
        existing = _read_purge_pending(path, expected_board_id=board_id)
        if existing != pending:
            raise LifecycleError("another purge journal already owns this Board ID")
        return path, existing
    atomic_write_json(
        path,
        pending,
        fsync_dir=True,
        failpoint=getattr(store, "_failpoint", None),
        payload_hash_key="payloadHash",
    )
    return path, _read_purge_pending(path, expected_board_id=board_id)


def _publish_tombstone(
    store: JsonBoardStore,
    board_id: str,
    document: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    root = _lkb_root_for_store(store)
    path = tombstone_path(root, board_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _safe_chain(root, path.parent) or (
        path.exists() and not _safe_chain(root, path)
    ):
        raise LifecycleError(f"unsafe tombstone publication path: {path}")
    if path.exists():
        existing = read_tombstone(path, expected_board_id=board_id)
        expected_links = {
            key: document[key]
            for key in (
                "purgeId",
                "sourceStoreRevision",
                "sourcePayloadHash",
                "purgedBy",
                "reason",
            )
        }
        if any(existing.get(key) != value for key, value in expected_links.items()):
            raise LifecycleError("another purge tombstone already owns this Board ID")
        return path, existing
    _hit(store, "purge_before_tombstone")
    atomic_write_json(
        path,
        document,
        fsync_dir=True,
        failpoint=getattr(store, "_failpoint", None),
        payload_hash_key="payloadHash",
    )
    verified = read_tombstone(path, expected_board_id=board_id)
    _hit(store, "purge_after_tombstone")
    return path, verified


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _contained(root: Path, path: Path) -> bool:
    root_abs = _lexical_absolute(root)
    path_abs = _lexical_absolute(path)
    try:
        return os.path.commonpath((root_abs, path_abs)) == os.fspath(root_abs)
    except ValueError:
        return False


def _safe_chain(root: Path, target: Path, *, descendants: bool = False) -> bool:
    root_abs = _lexical_absolute(root)
    target_abs = _lexical_absolute(target)
    if not _contained(root_abs, target_abs):
        return False
    try:
        relative = target_abs.relative_to(root_abs)
    except ValueError:
        return False
    current = root_abs
    if _is_reparse(current):
        return False
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse(current):
            return False
    if descendants and target_abs.is_dir():
        try:
            for directory, dirs, files in os.walk(target_abs, followlinks=False):
                directory_path = Path(directory)
                for name in (*dirs, *files):
                    if _is_reparse(directory_path / name):
                        return False
        except OSError:
            return False
    return True


def _remove_managed_purge_data(
    store: JsonBoardStore,
    board_id: str,
    operation_id: str,
    pending: dict[str, Any],
    *,
    active_watchers: int,
) -> None:
    board_dir = Path(getattr(store, "_board_dir"))
    root = _lkb_root_for_store(store)
    if active_watchers or int(getattr(store, "_active_watchers", 0)):
        raise LifecycleTransitionDenied(
            board_id, "purging", "purged", "active watcher prevents purge"
        )
    with getattr(store, "_lock"):
        envelope = getattr(store, "_load_locked")()
        operation = envelope.lifecycle.get("purge_operation")
        if (
            board_lifecycle_state(envelope) != "purging"
            or not isinstance(operation, dict)
            or operation.get("purge_id") != operation_id
            or _has_active_claims(envelope)
        ):
            raise LifecycleError("purge state changed before managed deletion")
        marker = pending["tombstone"]
        if (
            marker.get("purgeId") != operation_id
            or marker.get("sourceStoreRevision") != envelope.store_revision
            or marker.get("sourcePayloadHash") != envelope.integrity.get("payloadHash")
        ):
            raise LifecycleError("purge journal no longer matches managed data")
        if not _safe_chain(root, board_dir, descendants=True):
            raise LifecycleError("unsafe board path prevents purge")
        archive_dir = root / "archives"
        from .board_resolver import safe_board_id

        board_archives = archive_dir / safe_board_id(board_id)
        if board_archives.exists():
            if not _safe_chain(root, board_archives, descendants=True):
                raise LifecycleError("unsafe archive path prevents purge")
            _verify_archive_tree(board_archives, board_id=board_id)
        _hit(store, "purge_before_delete")
        entries = sorted(
            board_dir.iterdir(), key=lambda item: (item.name == "board.json", item.name)
        )
        for entry in entries:
            if entry.name in {".lock", ".lock.owner.json"}:
                continue
            if not _safe_chain(root, entry, descendants=entry.is_dir()):
                raise LifecycleError(f"unsafe managed purge target: {entry}")
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        if board_archives.is_dir():
            shutil.rmtree(board_archives)
        _hit(store, "purge_after_delete")
    # The permanent .lock anchor is deliberately retained.  The owner file
    # is removed by BoardFileLock while it still owns the same anchor inode.


def _verify_archive_tree(path: Path, *, board_id: str) -> None:
    for entry in path.iterdir():
        if entry.name == ".tmp" and entry.is_dir():
            if any(entry.iterdir()):
                raise LifecycleError("unverified archive temporary files prevent purge")
            continue
        if not entry.is_file() or entry.suffix != ".json":
            raise LifecycleError(f"unverified archive entry prevents purge: {entry}")
        read_archive(entry, expected_board_id=board_id)


def _finish_tombstoned_cleanup(
    store: JsonBoardStore,
    board_id: str,
    marker: Path | None,
    *,
    active_watchers: int,
) -> None:
    """Resume cleanup when a crash removed board.json before other data."""
    if active_watchers or int(getattr(store, "_active_watchers", 0)):
        raise LifecycleTransitionDenied(
            board_id, "purged", "purged", "active watcher prevents purge recovery"
        )
    board_dir = Path(getattr(store, "_board_dir"))
    root = _lkb_root_for_store(store)
    if marker is not None:
        read_tombstone(marker, expected_board_id=board_id)
    with getattr(store, "_lock"):
        if not _safe_chain(root, board_dir, descendants=True):
            raise LifecycleError("unsafe board path prevents purge recovery")
        for entry in list(board_dir.iterdir()):
            if entry.name in {".lock", ".lock.owner.json"}:
                continue
            if not _safe_chain(root, entry, descendants=entry.is_dir()):
                raise LifecycleError(f"unsafe purge recovery target: {entry}")
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink(missing_ok=True)
        from .board_resolver import safe_board_id

        archive_dir = root / "archives" / safe_board_id(board_id)
        if archive_dir.is_dir():
            if not _safe_chain(root, archive_dir, descendants=True):
                raise LifecycleError("unsafe archive path prevents purge recovery")
            _verify_archive_tree(archive_dir, board_id=board_id)
            shutil.rmtree(archive_dir)


def purge_board(
    store: JsonBoardStore,
    board_id: str,
    *,
    actor: str,
    command_id: str,
    request_hash: str,
    reason: str,
    confirm: str,
    authorized: bool = False,
    active_watchers: int = 0,
) -> CommandResult:
    """Two-phase purge ending only after tombstone publication and data removal."""
    if confirm != board_id:
        raise ValueError("purge confirmation must exactly match board_id")
    if not reason.strip():
        raise ValueError("purge reason is required")
    if not authorized:
        raise PermissionError("purge requires independent administrative permission")
    root = _lkb_root_for_store(store)
    board_directory = Path(getattr(store, "_board_dir"))
    if not _safe_chain(root, board_directory, descendants=True):
        raise LifecycleTransitionDenied(
            board_id,
            "unknown",
            "purging",
            "unsafe board path prevents purge",
        )
    marker = tombstone_path(root, board_id)
    pending_path = _purge_pending_path(root, board_id)
    if not store.exists():
        if marker.is_file():
            read_tombstone(marker, expected_board_id=board_id)
            _finish_tombstoned_cleanup(
                store,
                board_id,
                marker,
                active_watchers=active_watchers,
            )
            pending_path.unlink(missing_ok=True)
            return CommandResult(decision="committed", command_id=command_id, reason=reason)
        pending = _read_purge_pending(pending_path, expected_board_id=board_id)
        _finish_tombstoned_cleanup(
            store,
            board_id,
            None,
            active_watchers=active_watchers,
        )
        marker, tombstone = _publish_tombstone(
            store,
            board_id,
            pending["tombstone"],
        )
        pending_path.unlink(missing_ok=True)
        return CommandResult(
            decision="committed",
            command_id=command_id,
            reason=str(tombstone["reason"]),
            derived_facts=(f"tombstone:{marker}",),
        )
    if marker.is_file():
        read_tombstone(marker, expected_board_id=board_id)
        with getattr(store, "_lock"):
            current = getattr(store, "_load_locked")()
    else:
        current = store.load()
    state = board_lifecycle_state(current)
    if active_watchers or int(getattr(store, "_active_watchers", 0)):
        raise LifecycleTransitionDenied(
            board_id, state, "purging", "active watcher prevents purge"
        )
    if _has_active_claims(current):
        raise LifecycleTransitionDenied(board_id, state, "purging", "active claims exist")
    archive_info = current.lifecycle.get("archive_info")
    if archive_info is not None:
        if not isinstance(archive_info, dict) or not archive_info.get("archive_path"):
            raise LifecycleTransitionDenied(
                board_id, state, "purging", "archive has not been verified"
            )
        archive = read_archive(
            Path(str(archive_info["archive_path"])), expected_board_id=board_id
        )
        if archive.get("payloadHash") != archive_info.get("archive_hash"):
            raise LifecycleTransitionDenied(
                board_id, state, "purging", "archive provenance does not verify"
            )
    from .board_resolver import safe_board_id

    archive_tree = root / "archives" / safe_board_id(board_id)
    if archive_tree.exists():
        if not _safe_chain(root, archive_tree, descendants=True):
            raise LifecycleTransitionDenied(
                board_id, state, "purging", "unsafe archive path prevents purge"
            )
        try:
            _verify_archive_tree(archive_tree, board_id=board_id)
        except LifecycleError as exc:
            raise LifecycleTransitionDenied(
                board_id, state, "purging", f"unverified archive prevents purge: {exc}"
            ) from exc

    if state == "trashed":
        operation_id = uuid.uuid4().hex

        def prepare(envelope: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
            candidate = transition(envelope, "purging", actor=actor, reason=reason)
            candidate.lifecycle["purge_operation"] = {
                "purge_id": operation_id,
                "actor": actor,
                "reason": reason,
                "started_at": _now_iso(),
            }
            return candidate, CommandResult(
                decision="committed", command_id=f"{command_id}:prepare", reason=reason
            )

        _execute_lifecycle(
            store,
            board_id,
            f"{command_id}:prepare",
            f"{request_hash}:prepare",
            prepare,
            actor=actor,
            reason=reason,
        )
        _hit(store, "purge_after_prepare")
    elif state != "purging":
        raise LifecycleTransitionDenied(board_id, state, "purging", "board must be trashed")

    if marker.is_file():
        with getattr(store, "_lock"):
            purging = getattr(store, "_load_locked")()
    else:
        purging = store.load()
    operation = purging.lifecycle.get("purge_operation")
    if not isinstance(operation, dict) or not operation.get("purge_id"):
        raise LifecycleError("purging board has no resumable purge operation")
    operation_id = str(operation["purge_id"])
    operation_actor = str(operation.get("actor", actor))
    operation_reason = str(operation.get("reason", reason))
    with getattr(store, "_lock"):
        latest = getattr(store, "_load_locked")()
        latest_operation = latest.lifecycle.get("purge_operation")
        if (
            board_lifecycle_state(latest) != "purging"
            or not isinstance(latest_operation, dict)
            or latest_operation.get("purge_id") != operation_id
        ):
            raise LifecycleError("purge state changed before managed deletion")
        tombstone_document = _tombstone_document(
            board_id,
            latest,
            operation_id,
            actor=operation_actor,
            reason=operation_reason,
            purged_at=str(latest_operation.get("started_at", "")),
        )
        pending_path, pending = _write_purge_pending(
            store,
            board_id,
            tombstone_document,
        )
    _hit(store, "purge_after_pending")
    _remove_managed_purge_data(
        store,
        board_id,
        operation_id,
        pending,
        active_watchers=active_watchers,
    )
    marker, _ = _publish_tombstone(
        store,
        board_id,
        tombstone_document,
    )
    pending_path.unlink(missing_ok=True)
    return CommandResult(
        decision="committed",
        command_id=command_id,
        reason=operation_reason,
        derived_facts=(f"tombstone:{marker}",),
    )


@dataclass(frozen=True)
class GcCandidate:
    path: Path
    kind: str
    age_seconds: float
    reason: str
    size_bytes: int = 0
    action: str = "report"
    root: Path | None = None
    board_dir: Path | None = None
    observed_path: Path | None = None
    observed_mtime_ns: int | None = None
    observed_size: int | None = None
    observed_inode: int | None = None
    observed_hash: str = ""


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return f"sha256:{digest.hexdigest()}"


def _observe(path: Path) -> tuple[int, int, int, str] | None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return None
    value_hash = _file_hash(path) if stat.S_ISREG(info.st_mode) else ""
    return info.st_mtime_ns, info.st_size, info.st_ino, value_hash


def _candidate(
    path: Path,
    kind: str,
    age: float,
    reason: str,
    *,
    action: str,
    root: Path,
    board_dir: Path,
    observed_path: Path | None = None,
) -> GcCandidate:
    subject = observed_path or path
    observed = _observe(subject)
    if observed is None:
        return GcCandidate(path, "unsafe_path", 0, "stat failed; retained", root=root)
    mtime, size, inode, value_hash = observed
    return GcCandidate(
        path=path,
        kind=kind,
        age_seconds=age,
        reason=reason,
        size_bytes=size,
        action=action,
        root=root,
        board_dir=board_dir,
        observed_path=subject,
        observed_mtime_ns=mtime,
        observed_size=size,
        observed_inode=inode,
        observed_hash=value_hash,
    )


def _age(path: Path, now: float) -> float | None:
    observed = _observe(path)
    if observed is None:
        return None
    age = now - observed[0] / 1_000_000_000
    return age if age >= 0 else None


def _read_board_header(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        board = data.get("board")
        lifecycle = data.get("lifecycle")
        if not isinstance(board, dict) or not isinstance(lifecycle, dict):
            return None
        board_id = board.get("board_id")
        if not isinstance(board_id, str) or not board_id:
            return None
        from .board_resolver import safe_board_id

        if path.parent.name != safe_board_id(board_id):
            return None
        validate_board_envelope(data, board_id=board_id, verify_hash=True)
        project_uri = str(board.get("project_uri", ""))
        scope = lifecycle.get("scope")
        if (scope == "session") != project_uri.startswith("session:"):
            return None
    except (OSError, json.JSONDecodeError, ValueError, AssertionError):
        return None
    return data


def _claims_active(data: dict[str, Any]) -> bool:
    claims = data.get("claims", {})
    return isinstance(claims, dict) and any(
        isinstance(value, dict) and value.get("status") == "active"
        for value in claims.values()
    )


def _managed_temp(path: Path) -> bool:
    return path.is_file() and path.name.startswith(".") and path.name.endswith(".tmp")


def _collect_board_candidates(
    root: Path,
    board_dir: Path,
    candidates: list[GcCandidate],
    *,
    now: float,
    open_board_ids: Collection[str],
) -> None:
    if not _safe_chain(root, board_dir):
        candidates.append(
            GcCandidate(
                board_dir,
                "unsafe_path",
                0,
                "symlink/junction/reparse or escape refused",
                root=root,
                board_dir=board_dir,
            )
        )
        return
    board_json = board_dir / "board.json"
    data = _read_board_header(board_json) if board_json.is_file() else None
    if board_json.is_file() and data is None:
        candidates.append(
            GcCandidate(
                board_json,
                "invalid_board",
                0,
                "schema, identity, lifecycle scope, or payload hash invalid; retained",
                action="report",
                root=root,
                board_dir=board_dir,
            )
        )
        return
    lifecycle = (data or {}).get("lifecycle", {})
    state = str(lifecycle.get("state", "unknown")) if isinstance(lifecycle, dict) else "unknown"
    board_id = str((data or {}).get("board", {}).get("board_id", ""))
    busy = (
        state in {"archiving", "purging"}
        or (data is not None and _claims_active(data))
        or board_id in open_board_ids
    )

    tmp_dir = board_dir / ".tmp"
    if tmp_dir.is_dir() and _safe_chain(root, tmp_dir) and not busy:
        for item in tmp_dir.iterdir():
            if not _safe_chain(root, item):
                candidates.append(
                    GcCandidate(
                        item,
                        "unsafe_path",
                        0,
                        "unsafe temp entry refused",
                        root=root,
                        board_dir=board_dir,
                    )
                )
                continue
            age = _age(item, now)
            if age is not None and age >= GC_TEMP_AGE_SECONDS:
                kind = "temp" if _managed_temp(item) else "temp_suspicious"
                candidates.append(
                    _candidate(
                        item,
                        kind,
                        age,
                        "expired atomic temp" if kind == "temp" else "unrecognized old temp",
                        action="delete" if kind == "temp" else "quarantine",
                        root=root,
                        board_dir=board_dir,
                    )
                )

    quarantine = board_dir / "quarantine"
    if quarantine.is_dir() and _safe_chain(root, quarantine):
        for item in quarantine.iterdir():
            if not _safe_chain(root, item):
                continue
            age = _age(item, now)
            if age is not None and age >= GC_QUARANTINE_AGE_SECONDS:
                candidates.append(
                    _candidate(
                        item,
                        "quarantine",
                        age,
                        "expired quarantine requires explicit confirmation",
                        action="report",
                        root=root,
                        board_dir=board_dir,
                    )
                )

    scope = lifecycle.get("scope") if isinstance(lifecycle, dict) else None
    project_uri = str((data or {}).get("board", {}).get("project_uri", ""))
    if (
        data is not None
        and (scope == "session" or project_uri.startswith("session:"))
        and state == "active"
        and not busy
    ):
        age = _age(board_json, now)
        if age is not None and age >= GC_SESSION_ORPHAN_AGE_SECONDS:
            candidates.append(
                _candidate(
                    board_dir,
                    "session_orphan",
                    age,
                    "expired inactive session board",
                    action="delete",
                    root=root,
                    board_dir=board_dir,
                    observed_path=board_json,
                )
            )


def _observation_matches(candidate: GcCandidate) -> bool:
    subject = candidate.observed_path or candidate.path
    observed = _observe(subject)
    if observed is None:
        return False
    return observed == (
        candidate.observed_mtime_ns,
        candidate.observed_size,
        candidate.observed_inode,
        candidate.observed_hash,
    )


def _execute_gc_candidate(
    candidate: GcCandidate,
    *,
    now: float,
    open_board_ids: Collection[str],
) -> None:
    if candidate.action not in {"delete", "quarantine"}:
        return
    root = candidate.root
    board_dir = candidate.board_dir
    if root is None or board_dir is None:
        return
    from .file_lock import BoardFileLock

    with BoardFileLock(board_dir, timeout=0.25):
        if (
            not _safe_chain(root, board_dir, descendants=True)
            or not _safe_chain(root, candidate.path, descendants=candidate.path.is_dir())
            or not _observation_matches(candidate)
        ):
            return
        subject = candidate.observed_path or candidate.path
        age = _age(subject, now)
        threshold = (
            GC_SESSION_ORPHAN_AGE_SECONDS
            if candidate.kind == "session_orphan"
            else GC_TEMP_AGE_SECONDS
        )
        if age is None or age < threshold:
            return
        board_json = board_dir / "board.json"
        data = _read_board_header(board_json) if board_json.is_file() else None
        if board_json.is_file() and data is None:
            return
        lifecycle = (data or {}).get("lifecycle", {})
        state = (
            str(lifecycle.get("state", "unknown"))
            if isinstance(lifecycle, dict)
            else "unknown"
        )
        board_id = str((data or {}).get("board", {}).get("board_id", ""))
        if (
            state in {"archiving", "purging"}
            or (data is not None and _claims_active(data))
            or board_id in open_board_ids
        ):
            return
        if candidate.kind == "temp":
            if candidate.path.parent != board_dir / ".tmp" or not _managed_temp(candidate.path):
                return
            candidate.path.unlink(missing_ok=True)
        elif candidate.kind == "temp_suspicious":
            if candidate.path.parent != board_dir / ".tmp":
                return
            quarantine = board_dir / "quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            if not _safe_chain(root, quarantine):
                return
            destination = quarantine / candidate.path.name
            # Never replace an earlier quarantine artifact implicitly.
            if destination.exists() or not _safe_chain(root, destination):
                return
            os.replace(candidate.path, destination)
        elif candidate.kind == "session_orphan":
            scope = lifecycle.get("scope") if isinstance(lifecycle, dict) else None
            if data is None or scope != "session" or state != "active":
                return
            for entry in list(board_dir.iterdir()):
                if entry.name in {".lock", ".lock.owner.json"}:
                    continue
                if not _safe_chain(root, entry, descendants=entry.is_dir()):
                    return
            for entry in list(board_dir.iterdir()):
                if entry.name in {".lock", ".lock.owner.json"}:
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink(missing_ok=True)
    # Never unlink the permanent lock anchor after releasing its OS lock.


def gc_scan(
    root: Path | str,
    *,
    dry_run: bool = True,
    now: float | None = None,
    open_board_ids: Collection[str] = (),
) -> list[GcCandidate]:
    """Conservative GC with observed evidence and in-lock TOCTOU revalidation."""
    lkb_root = _lexical_absolute(Path(root))
    current = time.time() if now is None else now
    if not lkb_root.is_dir() or not _safe_chain(lkb_root, lkb_root):
        return []
    candidates: list[GcCandidate] = []
    boards = lkb_root / "boards"
    if boards.is_dir() and _safe_chain(lkb_root, boards):
        for board_dir in boards.iterdir():
            if board_dir.is_dir() or _is_reparse(board_dir):
                _collect_board_candidates(
                    lkb_root,
                    board_dir,
                    candidates,
                    now=current,
                    open_board_ids=open_board_ids,
                )
    # Project boards, archives, tombstones, and exports are never inferred as
    # automatic deletion candidates.
    candidates.sort(key=lambda item: item.age_seconds, reverse=True)
    if not dry_run:
        gc_apply(candidates, now=current, open_board_ids=open_board_ids)
    return candidates


def gc_apply(
    candidates: Collection[GcCandidate],
    *,
    now: float | None = None,
    open_board_ids: Collection[str] = (),
) -> None:
    """Apply previously observed candidates with full in-lock revalidation."""
    current = time.time() if now is None else now
    for candidate in candidates:
        _execute_gc_candidate(candidate, now=current, open_board_ids=open_board_ids)
