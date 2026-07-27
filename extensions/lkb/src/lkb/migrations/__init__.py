"""Schema migration framework for LKB board envelopes (spec §7.13).

Each migration is a pure function ``old_envelope_dict -> new_envelope_dict``
that transforms a raw envelope dict from one schema version to the next.
Migrations are idempotent: applying the same migration to an envelope that
is already at (or past) the target version is a no-op.

The :func:`migrate` registry walks the chain from the current
``schemaVersion`` up to *target_schema* (inclusive), applying each
migration exactly once.  Per spec §7.13:

* A backup of the original is saved before any migration runs.
* The final result is written via the full atomic-write protocol.
* If ``run-version < file-schema``, :class:`BoardSchemaTooNewError` is
  raised immediately (forward-compat guard, LKB-STORE-025).
* On failure, the original file is kept and the candidate is quarantined.

Phase 2 ships with a single ``v0_to_v1`` stub so the contract is testable:
v0 boards (``schemaVersion`` missing or 0) are upgraded to v1 by adding
the ``schemaVersion`` field plus the standard integrity block.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from lkb.atomic_file import atomic_write_json
from lkb.ir_hash import canonical_hash

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "STORE_FORMAT",
    "BoardSchemaTooNewError",
    "MigrationError",
    "MigrationOutcome",
    "migrate",
    "migrate_board_file",
    "register_migration",
    "v0_to_v1",
]

# ── constants (mirrored from json_store to avoid circular import) ────

STORE_FORMAT = "lkb-json-v1"
CURRENT_SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"


# ── error types (re-exported shape, separate class to avoid circular) ─


class BoardSchemaTooNewError(Exception):
    """Raised when the on-disk schema_version is newer than this code knows.

    This prevents an older reader from silently corrupting a board written
    by a newer version (LKB-STORE-025 / forward-compatibility guard).
    """

    def __init__(self, board_id: str, on_disk: int, supported: int) -> None:
        self.board_id = board_id
        self.on_disk_version = on_disk
        self.supported_version = supported
        super().__init__(
            f"Board {board_id!r} has schema_version={on_disk}, "
            f"but this build only supports up to {supported}"
        )


class MigrationError(Exception):
    """Raised when a migration step fails validation or produces an
    envelope that cannot be schema-validated."""


@dataclass(frozen=True)
class MigrationOutcome:
    """Diagnosable result of a successful on-disk migration."""

    board_path: Path
    backup_path: Path
    from_version: int
    to_version: int
    applied_versions: tuple[int, ...]


# ── migration registry ────────────────────────────────────────────────

# Maps (from_version -> to_version) -> migration function.
# Migration functions take a raw envelope dict and return a new dict.
_MIGRATIONS: dict[tuple[int, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_migration(
    from_version: int,
    to_version: int,
    func: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Register a migration from *from_version* to *to_version*.

    Migrations must form a linear chain starting at 0 and ending at
    ``CURRENT_SCHEMA_VERSION``.  Gaps are not allowed.
    """
    key = (from_version, to_version)
    if key in _MIGRATIONS:
        raise ValueError(f"Migration already registered for v{from_version} -> v{to_version}")
    _MIGRATIONS[key] = func


def _next_version(current: int) -> int | None:
    """Return the next version in the chain, or None if current is terminal."""
    for frm, to in _MIGRATIONS:
        if frm == current:
            return to
    return None


# ── public migrate entrypoint ─────────────────────────────────────────


def migrate(
    envelope_dict: dict[str, Any],
    *,
    target_schema: int = CURRENT_SCHEMA_VERSION,
) -> tuple[dict[str, Any], list[int]]:
    """Migrate *envelope_dict* up to *target_schema*.

    Returns ``(new_envelope_dict, applied_versions)`` where
    ``applied_versions`` is the list of schema versions that were
    transitioned *to* (e.g. ``[1]`` for a v0 -> v1 migration).

    Raises
    ------
    BoardSchemaTooNewError
        If the on-disk schema is newer than *target_schema* (the caller's
        code is too old to read this board — LKB-STORE-025).
    MigrationError
        If any migration step fails or the chain is incomplete.
    """
    current_version = int(envelope_dict.get("schemaVersion", 0))

    if current_version > target_schema:
        raise BoardSchemaTooNewError(
            str(envelope_dict.get("board", {}).get("board_id", "?")),
            current_version,
            target_schema,
        )

    if current_version == target_schema:
        return envelope_dict, []

    applied: list[int] = []
    current: dict[str, Any] = copy.deepcopy(envelope_dict)

    while current_version < target_schema:
        nxt = _next_version(current_version)
        if nxt is None:
            raise MigrationError(
                f"No migration registered from schema version {current_version} "
                f"(target is {target_schema})"
            )
        if nxt <= current_version:
            raise MigrationError(
                f"Migration chain is non-monotonic at v{current_version} -> v{nxt}"
            )
        if nxt > target_schema:
            raise MigrationError(
                f"Migration would overshoot target: v{current_version} -> v{nxt} "
                f"(target is {target_schema})"
            )

        func = _MIGRATIONS[(current_version, nxt)]
        try:
            current = func(current)
        except Exception as exc:  # noqa: BLE001
            raise MigrationError(f"Migration v{current_version} -> v{nxt} failed: {exc}") from exc

        # Post-condition: schemaVersion matches nxt
        new_version = int(current.get("schemaVersion", 0))
        if new_version != nxt:
            raise MigrationError(
                f"Migration v{current_version} -> v{nxt} produced envelope with "
                f"schemaVersion={new_version} (expected {nxt})"
            )

        applied.append(nxt)
        current_version = nxt

    return current, applied


# ── v0 -> v1 migration (stub, Phase 2) ───────────────────────────────


def v0_to_v1(env: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v0 (pre-schema-version) envelope to v1.

    v0 envelopes either lack ``schemaVersion`` entirely or have it set to 0.
    This migration:

    1. Sets ``schemaVersion`` to 1.
    2. Ensures ``storeFormat`` is ``lkb-json-v1``.
    3. Ensures ``storeRevision`` is present (default 0).
    4. Ensures standard collection fields exist with empty defaults.
    5. Computes and sets the ``integrity`` block with a valid payload hash.

    This is a no-op for envelopes that are already at v1 or higher.
    """
    current_version = int(env.get("schemaVersion", 0))
    if current_version >= 1:
        return env

    result: dict[str, Any] = copy.deepcopy(env)
    result["schemaVersion"] = 1
    result["storeFormat"] = env.get("storeFormat", STORE_FORMAT)
    if "storeRevision" not in result or not isinstance(result["storeRevision"], int):
        result["storeRevision"] = 0

    # Ensure required collection fields exist (proper defaults).
    for key, default in (
        ("board", {}),
        ("graphs", {}),
        ("nodes", {}),
        ("edges", {}),
        ("claims", {}),
        ("assertions", {}),
        ("evidence", {}),
        ("validationRuns", {}),
        ("processedCommands", {}),
        ("events", []),
        ("historySegments", []),
        (
            "lifecycle",
            {
                "state": "active",
                "scope": "project",
                "created_at": "",
                "updated_at": "",
                "closed_at": "",
                "archived_at": "",
                "retention_policy": "default",
                "origin_project_uri": "",
            },
        ),
    ):
        if key not in result:
            result[key] = copy.deepcopy(default)

    # Invalid legacy structure is a migration error, not permission to erase
    # unknown fields and synthesize an empty board.
    board = result.get("board")
    if not isinstance(board, dict):
        raise MigrationError("v0 board field must be an object")
    if "board_id" not in board:
        raise MigrationError("v0 board.board_id is required")
    if "policy" not in board:
        board["policy"] = {}
    result["board"] = board

    lifecycle = result.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise MigrationError("v0 lifecycle field must be an object")
    lifecycle_defaults = {
        "state": "active",
        "scope": (
            "session"
            if str(board.get("project_uri", "")).startswith("session:")
            else "project"
        ),
        "created_at": str(board.get("created_at", "")),
        "updated_at": str(board.get("updated_at", board.get("created_at", ""))),
        "closed_at": "",
        "archived_at": "",
        "retention_policy": "default",
        "origin_project_uri": str(board.get("project_uri", "")),
    }
    for key, value in lifecycle_defaults.items():
        lifecycle.setdefault(key, value)

    # v1 has a closed top-level schema.  Preserve legacy extension fields
    # under Board compatibility metadata instead of emitting a candidate the
    # Store will necessarily reject.
    v1_top_level = {
        "assertions",
        "board",
        "claims",
        "edges",
        "events",
        "evidence",
        "graphs",
        "historySegments",
        "integrity",
        "lifecycle",
        "nodes",
        "processedCommands",
        "schemaVersion",
        "storeFormat",
        "storeRevision",
        "validationRuns",
    }
    unknown = {
        key: result.pop(key)
        for key in tuple(result)
        if key not in v1_top_level
    }
    if unknown:
        compatibility = board.setdefault("compatibility_metadata", {})
        if not isinstance(compatibility, dict):
            raise MigrationError("board.compatibility_metadata must be an object")
        legacy = compatibility.setdefault("legacy_top_level", {})
        if not isinstance(legacy, dict):
            raise MigrationError(
                "board.compatibility_metadata.legacy_top_level must be an object"
            )
        for key, value in unknown.items():
            legacy.setdefault(key, value)

    # Compute and set payload hash (strip integrity first if present).
    result.pop("integrity", None)
    payload_hash_val = canonical_hash(result, algorithm=HASH_ALGORITHM)
    result["integrity"] = {
        "algorithm": HASH_ALGORITHM,
        "payloadHash": payload_hash_val,
    }

    return result


def _valid_v1_candidate(data: dict[str, Any], *, board_id: str) -> None:
    if data.get("storeFormat") != STORE_FORMAT or data.get("schemaVersion") != 1:
        raise MigrationError("candidate does not have the v1 store format/schema")
    if data.get("board", {}).get("board_id") != board_id:
        raise MigrationError("candidate Board ID changed during migration")
    if not isinstance(data.get("storeRevision"), int) or data["storeRevision"] < 0:
        raise MigrationError("candidate storeRevision is invalid")
    integrity = data.get("integrity")
    if not isinstance(integrity, dict):
        raise MigrationError("candidate integrity is missing")
    payload = {key: value for key, value in data.items() if key != "integrity"}
    if canonical_hash(payload) != integrity.get("payloadHash"):
        raise MigrationError("candidate payload hash is invalid")
    try:
        from lkb.json_store import validate_board_envelope

        validate_board_envelope(data, board_id=board_id, verify_hash=True)
    except Exception as exc:
        raise MigrationError(f"candidate fails Store schema/invariants: {exc}") from exc


def _hit(failpoint: Any | None, name: str) -> None:
    if failpoint is not None:
        failpoint.hit(name)


def migrate_board_file(
    board_path: Path | str,
    *,
    expected_board_id: str,
    target_schema: int = CURRENT_SCHEMA_VERSION,
    failpoint: Any | None = None,
) -> MigrationOutcome:
    """Store-callable migration orchestrator using the atomic write protocol.

    The original is first copied to a verifiable immutable migration backup.
    A failed candidate is retained in ``quarantine`` with a diagnostic sidecar;
    the original board path or backup always remains readable.
    """
    path = Path(board_path)
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read migration source {path}: {exc}") from exc
    if not isinstance(original, dict):
        raise MigrationError("migration source is not a JSON object")
    board_id = str(original.get("board", {}).get("board_id", ""))
    if board_id != expected_board_id:
        raise MigrationError(
            f"migration source Board ID {board_id!r} does not match {expected_board_id!r}"
        )
    from_version = int(original.get("schemaVersion", 0))
    if from_version == target_schema:
        return MigrationOutcome(path, path, from_version, from_version, ())
    source_digest = canonical_hash(original).split(":", 1)[-1][:16]
    backup_dir = path.parent / "migration-backups"
    backup_path = backup_dir / (
        f"{path.name}.schema-v{from_version}.{source_digest}.json"
    )
    operation_id = uuid.uuid4().hex
    stage = "backup"
    candidate: dict[str, Any] | None = None
    applied: list[int] = []
    try:
        _hit(failpoint, "migration_before_backup")
        if backup_path.exists():
            backed_up = json.loads(backup_path.read_text(encoding="utf-8"))
            if backed_up != original:
                raise MigrationError("immutable migration backup content mismatch")
        else:
            atomic_write_json(backup_path, original, fsync_dir=True)
        _hit(failpoint, "migration_after_backup")

        stage = "transform"
        candidate, applied = migrate(original, target_schema=target_schema)
        if not applied:
            return MigrationOutcome(path, backup_path, from_version, from_version, ())
        _hit(failpoint, "migration_after_transform")

        stage = "validate"
        _valid_v1_candidate(candidate, board_id=expected_board_id)
        _hit(failpoint, "migration_after_validate")

        stage = "publish"
        _hit(failpoint, "migration_before_publish")
        atomic_write_json(
            path,
            candidate,
            backup_path=path.with_name(f"{path.name}.bak"),
            fsync_dir=True,
            failpoint=failpoint,
            payload_hash_key="payloadHash",
        )
        _hit(failpoint, "migration_after_publish")
    except Exception as exc:
        quarantine = path.parent / "quarantine"
        stem = (
            f"{path.name}.migration-{operation_id}-"
            f"v{from_version}-v{target_schema}-{stage}"
        )
        candidate_path = quarantine / f"{stem}.candidate.json"
        diagnostic_path = quarantine / f"{stem}.error.json"
        atomic_write_json(
            candidate_path,
            candidate if candidate is not None else original,
            fsync_dir=True,
        )
        atomic_write_json(
            diagnostic_path,
            {
                "kind": "migration_failed",
                "source": str(path),
                "backup": str(backup_path),
                "fromVersion": from_version,
                "toVersion": target_schema,
                "stage": stage,
                "errorType": type(exc).__name__,
                "error": str(exc),
                "candidate": str(candidate_path),
            },
            fsync_dir=True,
        )
        raise MigrationError(
            f"migration v{from_version}->v{target_schema} failed; "
            f"source/backup preserved, candidate at {candidate_path}: {exc}"
        ) from exc
    return MigrationOutcome(
        path, backup_path, from_version, target_schema, tuple(applied)
    )


# ── bootstrap: register v0_to_v1 ──────────────────────────────────────

register_migration(0, 1, v0_to_v1)
