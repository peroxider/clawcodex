"""Board integrity doctor — diagnostics + safe repair (spec §7.12, §7.10).

The doctor inspects a board directory for problems and reports them as a
structured ``DoctorReport``.  When ``repair=True`` it performs only *safe*
fixes — things that cannot destroy user data:

  * Quarantine a corrupt ``board.json`` and restore a valid ``board.json.bak``
    (only when the backup is for the same board, has a valid payload hash,
    and has an explainable revision relationship).
  * Clean up confirmed-orphan ``.tmp/`` files older than the configured
    threshold (only when the board lock is held).
  * Resume stuck ``archiving`` / ``purging`` mid-states by rolling back to
    the last stable state (only when it can be done safely, without losing
    committed data).

It **never** auto-deletes:
  * Project boards
  * History segments
  * Archives
  * Exports

It also **never** breaks a live OS lock — ``.lock.owner.json`` staleness is
purely informational (LKB-STORE-020 / LKB-LIFE-018).

Spec §7.12 — corruption detection, backup, and recovery
Spec §7.10 — close / archive / restore / purge
Spec §7.9 — file lifecycle table

This module imports nothing from ToolContext or Task-v2 (spec §11.4 inv 12).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .atomic_file import atomic_write_json
from .board_resolver import board_dir, board_file_paths, safe_board_id
from .file_lock import BoardFileLock, BoardStoreBusyError
from .json_store import (
    BoardEnvelope,
    BoardStoreCorruptError,
    STORE_FORMAT,
    _validate_envelope_schema,  # pyright: ignore[reportPrivateUsage]
    _verify_payload_hash,  # pyright: ignore[reportPrivateUsage]
    payload_hash,
    set_payload_hash,
)
from .ir_hash import canonical_hash

__all__ = [
    "DoctorFinding",
    "DoctorReport",
    "FindingArea",
    "FindingSeverity",
    "doctor",
    "format_doctor_report",
    "DEFAULT_TMP_ORPHAN_THRESHOLD_SECONDS",
    "DEFAULT_QUARANTINE_THRESHOLD_SECONDS",
]

# ── default thresholds (spec §7.9) ────────────────────────────────────

DEFAULT_TMP_ORPHAN_THRESHOLD_SECONDS = 24 * 3600  # 24 hours
DEFAULT_QUARANTINE_THRESHOLD_SECONDS = 30 * 24 * 3600  # 30 days


# ── severity / area enums ─────────────────────────────────────────────


class FindingSeverity(str, Enum):
    """Severity of a doctor finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class FindingArea(str, Enum):
    """Broad area of the board storage that a finding relates to."""

    PRIMARY = "primary"  # board.json
    BACKUP = "backup"  # board.json.bak
    LIFECYCLE = "lifecycle"  # archiving / purging / trashed / etc.
    TMP = "tmp"  # .tmp/ orphan files
    HISTORY = "history"  # history segments
    QUARANTINE = "quarantine"  # quarantine directory / age
    LOCK = "lock"  # .lock / .lock.owner.json
    TOMBSTONE = "tombstone"  # tombstone files / age
    SCHEMA = "schema"  # schema version / migration


# ── finding / report data classes ────────────────────────────────────


@dataclass
class DoctorFinding:
    """A single finding from a doctor inspection."""

    severity: FindingSeverity
    area: FindingArea
    message: str
    auto_fixable: bool = False
    action_taken: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "area": self.area.value,
            "message": self.message,
            "auto_fixable": self.auto_fixable,
            "action_taken": self.action_taken,
        }


@dataclass
class DoctorReport:
    """Result of a doctor inspection (and optional repair) of a board."""

    board_id: str
    board_dir: Path
    findings: list[DoctorFinding] = field(default_factory=list)
    repair_attempted: bool = False
    board_state: str = "unknown"  # "healthy" | "recovered" | "corrupt" | "missing"

    # ── convenience helpers ──────────────────────────────────────────

    @property
    def is_healthy(self) -> bool:
        return all(
            f.severity != FindingSeverity.CRITICAL and f.severity != FindingSeverity.ERROR
            for f in self.findings
        )

    @property
    def has_errors(self) -> bool:
        return any(
            f.severity in (FindingSeverity.ERROR, FindingSeverity.CRITICAL) for f in self.findings
        )

    def add(
        self,
        severity: FindingSeverity,
        area: FindingArea,
        message: str,
        *,
        auto_fixable: bool = False,
        action_taken: str = "",
    ) -> DoctorFinding:
        f = DoctorFinding(
            severity=severity,
            area=area,
            message=message,
            auto_fixable=auto_fixable,
            action_taken=action_taken,
        )
        self.findings.append(f)
        return f

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_id": self.board_id,
            "board_dir": str(self.board_dir),
            "board_state": self.board_state,
            "repair_attempted": self.repair_attempted,
            "findings": [f.to_dict() for f in self.findings],
        }


# ── public API ────────────────────────────────────────────────────────


def doctor(
    board_id_or_dir: str | Path,
    *,
    repair: bool = False,
    home: Path | None = None,
    tmp_orphan_threshold_seconds: float = DEFAULT_TMP_ORPHAN_THRESHOLD_SECONDS,
    quarantine_threshold_seconds: float = DEFAULT_QUARANTINE_THRESHOLD_SECONDS,
) -> DoctorReport:
    """Inspect a board directory for integrity / lifecycle problems.

    Parameters
    ----------
    board_id_or_dir:
        Either a ``board_id`` string (resolved via ``board_dir``) or a
        ``Path`` to a board directory.  When a path is given, the
        ``board_id`` is read from the on-disk envelope (when possible).
    repair:
        If True, perform *safe* automatic repairs.  Default False
        (diagnostics only).
    home:
        Optional home directory override (only used when *board_id_or_dir*
        is a board_id string rather than a path).
    tmp_orphan_threshold_seconds:
        How old a ``.tmp/`` file must be before it is considered a
        confirmed orphan eligible for cleanup.  Default 24 hours.
    quarantine_threshold_seconds:
        How old files in ``quarantine/`` must be before the doctor
        reports them as aging.  Default 30 days.

    Returns
    -------
    DoctorReport
        Structured findings.  Does not raise for common error conditions —
        they are reported as findings instead.  Only raises for truly
        unexpected programming errors.
    """
    # Resolve input to a directory + tentative board_id.
    bdir, expected_board_id, from_path = _resolve_target(board_id_or_dir, home=home)
    report = DoctorReport(board_id=expected_board_id, board_dir=bdir)

    if not bdir.is_dir():
        report.board_state = "missing"
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.PRIMARY,
            f"Board directory does not exist: {bdir}",
        )
        return report

    # When input was a directory path, always derive paths from that
    # directory directly — don't re-resolve via board_id (which would
    # use the default home and might point to a different location).
    if from_path:
        paths = _path_map(bdir)
    else:
        paths = board_file_paths(expected_board_id, home=home)

    # Try to acquire the board lock.  If we can't (busy), we still do a
    # read-only inspection but we won't perform any repairs.
    lock = BoardFileLock(bdir, timeout=2.0)
    lock_acquired = False
    try:
        lock.acquire()
        lock_acquired = True
    except BoardStoreBusyError:
        report.add(
            FindingSeverity.WARNING,
            FindingArea.LOCK,
            "Board lock is currently held by another process; "
            "skipping locked-only checks and all repairs",
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        report.add(
            FindingSeverity.ERROR,
            FindingArea.LOCK,
            f"Failed to acquire board lock: {exc}",
        )

    try:
        _inspect_primary(report, paths)
        _inspect_backup(report, paths)
        _inspect_lifecycle(report, paths)
        _inspect_tmp_files(report, paths, tmp_orphan_threshold_seconds)
        _inspect_history_segments(report, paths)
        _inspect_quarantine(report, paths, quarantine_threshold_seconds)
        _inspect_lock_anchor(report, paths, lock_acquired)
        _inspect_tombstone(report, paths)

        # Determine overall state from findings so far.
        if _primary_is_healthy(report):
            report.board_state = "healthy"
        elif _primary_was_recovered(report):
            report.board_state = "recovered"
        else:
            report.board_state = "corrupt"

        # ── repair phase (only if lock is held and repair=True) ─────
        if repair and lock_acquired:
            report.repair_attempted = True
            _do_safe_repairs(report, paths, tmp_orphan_threshold_seconds)

    finally:
        if lock_acquired:
            try:
                lock.release()
            except Exception:
                pass

    return report


# ── human-readable report ─────────────────────────────────────────────


def format_doctor_report(report: DoctorReport) -> str:
    """Format a DoctorReport as a human-readable multi-line string."""
    lines: list[str] = []
    lines.append(f"Board:   {report.board_id}")
    lines.append(f"Path:    {report.board_dir}")
    lines.append(f"State:   {report.board_state}")
    lines.append(f"Repair:  {'attempted' if report.repair_attempted else 'not attempted'}")
    lines.append(f"Findings: {len(report.findings)}")
    lines.append("")
    if not report.findings:
        lines.append("  (no findings — board is clean)")
        return "\n".join(lines)
    for i, f in enumerate(report.findings, 1):
        sev = f.severity.value.upper()
        tag = f"[{sev}] {f.area.value}"
        lines.append(f"  {i:2d}. {tag}: {f.message}")
        if f.auto_fixable and not f.action_taken:
            lines.append(f"      → auto-fixable")
        if f.action_taken:
            lines.append(f"      → action: {f.action_taken}")
    return "\n".join(lines)


# ── inspection helpers ────────────────────────────────────────────────


def _inspect_primary(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Check board.json: existence, JSON, schema, board ID, payload hash."""
    p = paths["board_json"]
    if not p.is_file():
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.PRIMARY,
            f"board.json is missing: {p}",
            auto_fixable=False,
        )
        return

    data = _read_json_safe(p)
    if data is None:
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.PRIMARY,
            f"board.json is not valid JSON: {p}",
            auto_fixable=False,
        )
        return

    # Schema / structure check.
    try:
        _validate_envelope_schema(data, board_id=None)
    except Exception as exc:  # noqa: BLE001
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.SCHEMA,
            f"board.json fails schema validation: {exc}",
            auto_fixable=False,
        )
        return

    # board_id sanity check.
    envelope_bid = data.get("board", {}).get("board_id", "")
    if report.board_id and envelope_bid and envelope_bid != report.board_id:
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.PRIMARY,
            f"board_id mismatch: directory expects {report.board_id!r}, "
            f"envelope has {envelope_bid!r}",
            auto_fixable=False,
        )
        return

    # If we don't know the board_id yet, take it from the envelope.
    if not report.board_id and envelope_bid:
        report.board_id = envelope_bid

    # Payload hash verification.
    if not _verify_payload_hash(data):
        report.add(
            FindingSeverity.CRITICAL,
            FindingArea.PRIMARY,
            "board.json payload hash does not match content",
            auto_fixable=False,
        )
        return

    # Revision chain sanity: previousPayloadHash must match previous
    # revision if there is one — we can only check chain consistency if
    # we also have the .bak to compare against (done in _inspect_backup).
    report.add(
        FindingSeverity.INFO,
        FindingArea.PRIMARY,
        f"board.json is valid (store_revision={data.get('storeRevision', '?')})",
    )


def _inspect_backup(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Check board.json.bak and its relationship to the primary."""
    bak = paths["board_json_bak"]
    if not bak.is_file():
        report.add(
            FindingSeverity.INFO,
            FindingArea.BACKUP,
            "board.json.bak does not exist (board has never been updated)",
        )
        return

    data = _read_json_safe(bak)
    if data is None:
        report.add(
            FindingSeverity.WARNING,
            FindingArea.BACKUP,
            "board.json.bak is not valid JSON",
            auto_fixable=False,
        )
        return

    try:
        _validate_envelope_schema(data, board_id=report.board_id or None)
    except Exception as exc:  # noqa: BLE001
        report.add(
            FindingSeverity.WARNING,
            FindingArea.BACKUP,
            f"board.json.bak fails schema validation: {exc}",
            auto_fixable=False,
        )
        return

    if not _verify_payload_hash(data):
        report.add(
            FindingSeverity.WARNING,
            FindingArea.BACKUP,
            "board.json.bak payload hash does not match content",
            auto_fixable=False,
        )
        return

    bak_bid = data.get("board", {}).get("board_id", "")
    if report.board_id and bak_bid and bak_bid != report.board_id:
        report.add(
            FindingSeverity.WARNING,
            FindingArea.BACKUP,
            f"board.json.bak belongs to different board {bak_bid!r} (expected {report.board_id!r})",
            auto_fixable=False,
        )
        return

    # Revision relationship: backup revision must be <= primary revision
    # (if primary is valid).  If primary is corrupt we note that backup
    # is usable for recovery.
    bak_rev = data.get("storeRevision", 0)
    primary_rev = _primary_store_revision(paths)

    if primary_rev is not None:
        if bak_rev <= primary_rev:
            report.add(
                FindingSeverity.INFO,
                FindingArea.BACKUP,
                f"board.json.bak is valid (store_revision={bak_rev}, "
                f"primary={primary_rev}, explainable)",
            )
        else:
            report.add(
                FindingSeverity.WARNING,
                FindingArea.BACKUP,
                f"board.json.bak has store_revision={bak_rev} which is "
                f"newer than primary {primary_rev} — unexplainable",
                auto_fixable=False,
            )
    else:
        # Primary is missing / corrupt — backup looks recoverable.
        report.add(
            FindingSeverity.INFO,
            FindingArea.BACKUP,
            (
                "board.json.bak is valid and its chain relationship permits recovery "
                f"(store_revision={bak_rev})"
                if _backup_explains_invalid_primary(paths, data)
                else "board.json.bak is valid but cannot be proven to immediately "
                f"precede the invalid primary (store_revision={bak_rev})"
            ),
            auto_fixable=_backup_explains_invalid_primary(paths, data),
        )


def _inspect_lifecycle(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Inspect lifecycle state for stuck mid-states (archiving, purging)."""
    p = paths["board_json"]
    data = _read_json_safe(p)
    if data is None:
        return  # primary already reported as bad

    lifecycle = data.get("lifecycle", {})
    if not isinstance(lifecycle, dict):
        report.add(
            FindingSeverity.ERROR,
            FindingArea.LIFECYCLE,
            "lifecycle field is not a dict",
            auto_fixable=False,
        )
        return

    state = lifecycle.get("state", "active")
    if state in ("archiving", "purging"):
        report.add(
            FindingSeverity.WARNING,
            FindingArea.LIFECYCLE,
            f"Board is in mid-state '{state}' — a previous operation may have been interrupted",
            auto_fixable=True,
        )
    elif state == "trashed":
        report.add(
            FindingSeverity.INFO,
            FindingArea.LIFECYCLE,
            "Board is in 'trashed' state (grace period before purge)",
        )
    elif state in ("active", "closed", "archived"):
        report.add(
            FindingSeverity.INFO,
            FindingArea.LIFECYCLE,
            f"Lifecycle state is '{state}' (stable)",
        )
    else:
        report.add(
            FindingSeverity.WARNING,
            FindingArea.LIFECYCLE,
            f"Unknown lifecycle state: {state!r}",
            auto_fixable=False,
        )


def _inspect_tmp_files(
    report: DoctorReport,
    paths: dict[str, Path],
    threshold_seconds: float,
) -> None:
    """Check .tmp/ directory for orphaned temp files."""
    tmp_dir = paths["tmp_dir"]
    if not tmp_dir.is_dir():
        return

    now = time.time()
    orphans: list[Path] = []
    recent: list[Path] = []
    try:
        entries = list(tmp_dir.iterdir())
    except OSError:
        return

    for entry in entries:
        if not entry.is_file():
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        age = now - mtime
        if age > threshold_seconds:
            orphans.append(entry)
        else:
            recent.append(entry)

    if orphans:
        report.add(
            FindingSeverity.WARNING,
            FindingArea.TMP,
            f"Found {len(orphans)} orphaned .tmp/ file(s) older than "
            f"{threshold_seconds / 3600:.1f}h",
            auto_fixable=True,
        )
    if recent:
        report.add(
            FindingSeverity.INFO,
            FindingArea.TMP,
            f"Found {len(recent)} recent .tmp/ file(s) (under age threshold)",
        )


def _inspect_history_segments(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Check that history/ files referenced in historySegments actually exist,
    and that no orphan history files exist on disk."""
    hist_dir = paths["history_dir"]
    p = paths["board_json"]
    data = _read_json_safe(p)
    if data is None:
        return  # primary already reported as bad

    segments = data.get("historySegments", [])
    if not isinstance(segments, list):
        return

    referenced: set[str] = set()
    for seg in segments:
        if isinstance(seg, dict):
            fname = seg.get("file")
            if isinstance(fname, str) and fname:
                referenced.add(fname)

    # Check referenced files exist.
    missing_refs: list[str] = []
    for fname in referenced:
        fpath = hist_dir / fname
        if not fpath.is_file():
            missing_refs.append(fname)

    if missing_refs:
        report.add(
            FindingSeverity.ERROR,
            FindingArea.HISTORY,
            f"{len(missing_refs)} referenced history segment(s) missing from disk: "
            f"{', '.join(missing_refs[:3])}{'...' if len(missing_refs) > 3 else ''}",
            auto_fixable=False,
        )

    # Check for orphan files on disk.
    if hist_dir.is_dir():
        try:
            disk_files = {e.name for e in hist_dir.iterdir() if e.is_file()}
        except OSError:
            disk_files = set()
        orphans = disk_files - referenced
        if orphans:
            report.add(
                FindingSeverity.WARNING,
                FindingArea.HISTORY,
                f"{len(orphans)} orphan history file(s) on disk "
                f"(not referenced by historySegments)",
                auto_fixable=False,
            )


def _inspect_quarantine(
    report: DoctorReport,
    paths: dict[str, Path],
    threshold_seconds: float,
) -> None:
    """Report on quarantine directory contents and age."""
    qdir = paths["quarantine_dir"]
    if not qdir.is_dir():
        return

    try:
        entries = [e for e in qdir.iterdir() if e.is_file()]
    except OSError:
        return

    if not entries:
        return

    now = time.time()
    old_count = 0
    for e in entries:
        try:
            age = now - e.stat().st_mtime
            if age > threshold_seconds:
                old_count += 1
        except OSError:
            continue

    report.add(
        FindingSeverity.INFO,
        FindingArea.QUARANTINE,
        f"quarantine/ contains {len(entries)} file(s); "
        f"{old_count} older than {threshold_seconds / 86400:.0f} days",
    )


def _inspect_lock_anchor(
    report: DoctorReport,
    paths: dict[str, Path],
    lock_acquired: bool,
) -> None:
    """Check .lock anchor file and .lock.owner.json diagnostics.

    Per LKB-LIFE-018: a .lock file with no OS lock is fine — it's a
    permanent anchor.  We never delete it.  A stale .lock.owner.json
    when no OS lock is held is purely informational.
    """
    lock_file = paths["lock_file"]
    owner_file = paths["lock_owner_json"]

    if not lock_file.is_file():
        # .lock anchor missing — informational, will be created on next write.
        report.add(
            FindingSeverity.INFO,
            FindingArea.LOCK,
            ".lock anchor file is missing (will be created on next write)",
        )

    if owner_file.is_file():
        owner_data = _read_json_safe(owner_file)
        if owner_data is None:
            report.add(
                FindingSeverity.INFO,
                FindingArea.LOCK,
                ".lock.owner.json exists but is unparseable (diagnostic only)",
            )
            return

        pid = owner_data.get("pid", "?")
        acquired_at = owner_data.get("acquired_at", 0)
        try:
            age_s = time.time() - float(acquired_at)
        except (TypeError, ValueError):
            age_s = 0.0

        if lock_acquired:
            # We hold the lock — owner file should reflect us.
            report.add(
                FindingSeverity.INFO,
                FindingArea.LOCK,
                f".lock.owner.json present (pid={pid}, "
                f"age={age_s:.0f}s) — lock is held by this process",
            )
        else:
            # We could NOT acquire the lock, OR lock is available but
            # owner file is stale from a crashed process.
            report.add(
                FindingSeverity.INFO,
                FindingArea.LOCK,
                f".lock.owner.json is present (pid={pid}, "
                f"age={age_s:.0f}s) — diagnostic only; lock anchor not removed",
            )
    else:
        report.add(
            FindingSeverity.INFO,
            FindingArea.LOCK,
            ".lock.owner.json is not present (no active lock holder)",
        )


def _inspect_tombstone(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Look for tombstone files in the parent directory.

    Tombstones live outside the board directory (in a sibling
    ``tombstones/`` directory at the boards level).  We just check if any
    tombstone exists for this board and report its age.
    """
    # Board dir is .../lkb/boards/<safe-id>/
    # Tombs are at .../lkb/tombstones/<safe-id>.json
    boards_parent = report.board_dir.parent
    tomb_dir = boards_parent.parent / "tombstones"
    if not tomb_dir.is_dir():
        return

    safe_id = report.board_dir.name
    tomb_file = tomb_dir / f"{safe_id}.json"
    if not tomb_file.is_file():
        return

    try:
        age = time.time() - tomb_file.stat().st_mtime
    except OSError:
        age = 0.0

    report.add(
        FindingSeverity.INFO,
        FindingArea.TOMBSTONE,
        f"Tombstone exists for this board (age={age / 86400:.1f} days)",
    )


# ── repair helpers ────────────────────────────────────────────────────


def _do_safe_repairs(
    report: DoctorReport,
    paths: dict[str, Path],
    tmp_threshold_seconds: float,
) -> None:
    """Perform safe, data-preserving repairs.

    Order matters:
      1. Restore from backup (if primary is corrupt and backup is valid)
      2. Clean confirmed-orphan .tmp/ files
      3. Roll back stuck lifecycle mid-states (archiving → active)

    All repairs use proper locking (caller holds the lock) and follow
    atomic-write semantics where appropriate.
    """
    # 1. Backup recovery (primary corrupt + backup valid)
    _repair_restore_from_backup(report, paths)

    # 2. Orphan .tmp cleanup
    _repair_clean_tmp_orphans(report, paths, tmp_threshold_seconds)

    # 3. Stuck lifecycle mid-state rollback
    _repair_stuck_lifecycle(report, paths)


def _repair_restore_from_backup(report: DoctorReport, paths: dict[str, Path]) -> None:
    """If primary is corrupt and backup is valid, quarantine primary and
    install backup as primary.

    Only runs when:
      - primary is missing / corrupt (critical finding in PRIMARY area)
      - backup is valid and same board
      - backup revision is "explainable" (we accept any valid backup —
        if primary is corrupt we can't compare revisions, but spec §7.12
        says "explainable revision"; we at least verify the backup has
        a valid payload hash and same board_id)
    """
    # Only act if primary has a critical finding and backup is usable.
    primary_critical = any(
        f.area == FindingArea.PRIMARY and f.severity == FindingSeverity.CRITICAL
        for f in report.findings
    )
    backup_info = _get_backup_validity(paths)

    if not primary_critical or backup_info is None:
        return

    bak_data, bak_rev, bak_bid = backup_info

    # Same board check.
    if report.board_id and bak_bid and bak_bid != report.board_id:
        return
    if not _backup_explains_invalid_primary(paths, bak_data):
        report.add(
            FindingSeverity.WARNING,
            FindingArea.BACKUP,
            "Automatic recovery refused: invalid primary does not prove that "
            "board.json.bak is its immediate predecessor",
            auto_fixable=False,
        )
        return

    # Perform the recovery.
    board_json = paths["board_json"]
    qdir = paths["quarantine_dir"]

    try:
        qdir.mkdir(parents=True, exist_ok=True)
        # Quarantine a byte-for-byte specimen without creating a gap in the
        # authoritative path.
        if board_json.exists():
            stamp = time.time_ns()
            target = qdir / f"board.json.{stamp}.primary-corrupt"
            shutil.copy2(board_json, target)

        recovered = BoardEnvelope.from_dict(bak_data)
        previous_hash = str(recovered.integrity.get("payloadHash", ""))
        recovered.store_revision = bak_rev + 1
        recovered.board["store_revision"] = recovered.store_revision
        recovered.events.append(
            {
                "type": "store_recovered",
                "actor": "doctor",
                "reason": "primary invalid; restored from board.json.bak",
                "recovered_from_store_revision": bak_rev,
                "store_revision": recovered.store_revision,
            }
        )
        set_payload_hash(recovered, previous_hash=previous_hash)
        recovered_data = recovered.to_dict()
        _validate_envelope_schema(recovered_data, board_id=bak_bid)
        atomic_write_json(
            board_json,
            recovered_data,
            backup_path=None,
            payload_hash_key="payloadHash",
        )

        # Verify the restored file.
        restored = _read_json_safe(board_json)
        if restored is None or not _verify_payload_hash(restored):
            # Recovery didn't take — revert by re-copying from backup
            # (shouldn't happen, but be defensive).
            raise RuntimeError("restored board.json failed hash verification")

        report.add(
            FindingSeverity.WARNING,
            FindingArea.PRIMARY,
            f"Restored board.json from backup and recorded Recovery Event "
            f"(store_revision={recovered.store_revision})",
            action_taken=f"restored from board.json.bak (rev {bak_rev}); user warning emitted",
        )
        report.board_state = "recovered"

    except Exception as exc:  # noqa: BLE001
        report.add(
            FindingSeverity.ERROR,
            FindingArea.PRIMARY,
            f"Failed to restore from backup: {exc}",
            action_taken="recovery attempt failed",
        )


def _repair_clean_tmp_orphans(
    report: DoctorReport,
    paths: dict[str, Path],
    threshold_seconds: float,
) -> None:
    """Delete .tmp/ files older than the threshold.

    Only safe because:
      - Temp files are never authoritative (spec §7.5).
      - We hold the board lock, so no in-progress write exists.
      - We only delete files older than the threshold, so we don't
        interfere with concurrent operations (though the lock already
        prevents those).
    """
    tmp_dir = paths["tmp_dir"]
    if not tmp_dir.is_dir():
        return

    now = time.time()
    deleted = 0
    failed = 0
    try:
        entries = list(tmp_dir.iterdir())
    except OSError:
        return

    for entry in entries:
        if not entry.is_file():
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age > threshold_seconds:
            try:
                entry.unlink()
                deleted += 1
            except OSError:
                failed += 1

    if deleted:
        report.add(
            FindingSeverity.INFO,
            FindingArea.TMP,
            f"Cleaned {deleted} orphaned .tmp/ file(s) "
            f"(older than {threshold_seconds / 3600:.1f}h)"
            + (f", {failed} failed" if failed else ""),
            action_taken=f"deleted {deleted} orphan .tmp file(s)",
        )


def _repair_stuck_lifecycle(report: DoctorReport, paths: dict[str, Path]) -> None:
    """Roll back stuck ``archiving`` / ``purging`` mid-states.

    For ``archiving``: the archive file may or may not have been written
    to archives/.  The safe rollback is to return the board to its
    previous stable state (``active`` / ``closed``) — if an archive
    exists, it's an immutable snapshot and can be left there.

    For ``purging``: we do NOT auto-recover — purging is destructive and
    we don't know how far it got.  We just report it as stuck.
    """
    p = paths["board_json"]
    data = _read_json_safe(p)
    if data is None:
        return

    lifecycle = data.get("lifecycle", {})
    if not isinstance(lifecycle, dict):
        return

    state = lifecycle.get("state")
    if state == "archiving":
        # Safe rollback: return to active (previous stable state).
        # We don't delete any partial archive file — it's harmless.
        try:
            _validate_envelope_schema(data, board_id=report.board_id or None)
            if not _verify_payload_hash(data):
                raise ValueError("stuck archiving primary has invalid payload hash")
            env = BoardEnvelope.from_dict(data)
            previous_hash = str(env.integrity.get("payloadHash", ""))
            previous_revision = env.store_revision
            operation = env.lifecycle.get("archive_operation")
            operation_id = (
                str(operation.get("operation_id", ""))
                if isinstance(operation, dict)
                else ""
            )
            env.lifecycle = dict(env.lifecycle)
            env.lifecycle["state"] = "closed"
            env.lifecycle["updated_at"] = _iso_now()
            env.lifecycle["archiving_interrupted"] = True
            env.lifecycle["archive_recovery"] = {
                "action": "rolled_back_to_closed",
                "operation_id": operation_id,
                "recovered_at": env.lifecycle["updated_at"],
            }
            env.store_revision = previous_revision + 1
            env.board["store_revision"] = env.store_revision
            env.events.append(
                {
                    "type": "lifecycle_recovered",
                    "actor": "doctor",
                    "from_state": "archiving",
                    "to_state": "closed",
                    "reason": "stuck archive operation rolled back to legal predecessor",
                    "archive_operation_id": operation_id,
                    "store_revision": env.store_revision,
                }
            )
            command_id = f"doctor:recover-archiving:{previous_revision}"
            env.processed_commands[command_id] = {
                "command_id": command_id,
                "request_hash": canonical_hash(
                    {
                        "kind": "doctor_recover_archiving",
                        "board_id": env.board_id(),
                        "source_store_revision": previous_revision,
                        "archive_operation_id": operation_id,
                    }
                ),
                "decision": "committed",
                "actor": "doctor",
                "store_revision": env.store_revision,
                "reason": "rolled back stuck archiving to closed",
                "derived_facts": [],
                "revision_vector": env.current_revision_vector().to_dict(),
            }
            set_payload_hash(env, previous_hash=previous_hash)
            final_data = env.to_dict()
            _validate_envelope_schema(final_data, board_id=env.board_id())

            # Atomic write.
            atomic_write_json(
                p,
                final_data,
                backup_path=paths["board_json_bak"],
                payload_hash_key="payloadHash",
            )

            report.add(
                FindingSeverity.INFO,
                FindingArea.LIFECYCLE,
                "Committed recovery of stuck 'archiving' state to 'closed'",
                action_taken=(
                    "created a new revision with Recovery/Lifecycle event and "
                    "reverted lifecycle.state from archiving to closed"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            report.add(
                FindingSeverity.ERROR,
                FindingArea.LIFECYCLE,
                f"Failed to roll back stuck archiving state: {exc}",
                action_taken="rollback attempt failed",
            )

    elif state == "purging":
        # We don't auto-recover purging — it's destructive and
        # we can't know how far it got.  Just report.
        report.add(
            FindingSeverity.WARNING,
            FindingArea.LIFECYCLE,
            "Board is stuck in 'purging' state — manual intervention required "
            "(auto-repair skipped: purge is destructive)",
            auto_fixable=False,
        )


# ── utility helpers ───────────────────────────────────────────────────


def _resolve_target(
    board_id_or_dir: str | Path,
    *,
    home: Path | None = None,
) -> tuple[Path, str, bool]:
    """Resolve the input into (board_dir, expected_board_id, from_path).

    *from_path* is True when the input was a filesystem path (rather than
    a board_id string).  The caller uses this to decide whether to
    derive sub-paths from the directory directly or via
    ``board_file_paths``.

    If the input looks like a path that exists, treat it as a board
    directory and derive the board_id by attempting to read board.json.
    Otherwise treat it as a board_id and resolve via board_dir().
    """
    p = Path(board_id_or_dir) if isinstance(board_id_or_dir, str) else board_id_or_dir

    # If it's an existing directory, treat as board dir.
    if p.is_dir():
        board_json = p / "board.json"
        bid = ""
        data = _read_json_safe(board_json)
        if data is not None:
            bid = str(data.get("board", {}).get("board_id", ""))
        return p, bid, True

    # If it's a Path object or a string with path separators, treat as
    # board directory (but report missing).
    if isinstance(board_id_or_dir, Path) or (
        isinstance(board_id_or_dir, str) and ("/" in board_id_or_dir or "\\" in board_id_or_dir)
    ):
        return p, "", True

    # Otherwise treat as board_id.
    bid = str(board_id_or_dir)
    return board_dir(bid, home=home), bid, False


def _path_map(bdir: Path) -> dict[str, Path]:
    """Build a paths dict for a board directory (without knowing board_id)."""
    return {
        "board_json": bdir / "board.json",
        "board_json_bak": bdir / "board.json.bak",
        "lock_file": bdir / ".lock",
        "lock_owner_json": bdir / ".lock.owner.json",
        "tmp_dir": bdir / ".tmp",
        "history_dir": bdir / "history",
        "quarantine_dir": bdir / "quarantine",
    }


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file.  Returns None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _primary_store_revision(paths: dict[str, Path]) -> int | None:
    """Return storeRevision of primary, or None if unreadable."""
    data = _read_json_safe(paths["board_json"])
    if data is None:
        return None
    rev = data.get("storeRevision")
    if isinstance(rev, int):
        return rev
    return None


def _backup_explains_invalid_primary(
    paths: dict[str, Path],
    backup: dict[str, Any],
) -> bool:
    """Return whether raw primary metadata proves an immediate hash-chain link."""
    primary = _read_json_safe(paths["board_json"])
    if primary is None:
        return False
    primary_revision = primary.get("storeRevision")
    backup_revision = backup.get("storeRevision")
    primary_integrity = primary.get("integrity")
    backup_integrity = backup.get("integrity")
    primary_board = primary.get("board")
    backup_board = backup.get("board")
    if not all(
        isinstance(value, dict)
        for value in (primary_integrity, backup_integrity, primary_board, backup_board)
    ):
        return False
    return (
        isinstance(primary_revision, int)
        and isinstance(backup_revision, int)
        and primary_revision == backup_revision + 1
        and primary_integrity.get("previousPayloadHash")
        == backup_integrity.get("payloadHash")
        and primary_board.get("board_id") == backup_board.get("board_id")
    )


def _primary_is_healthy(report: DoctorReport) -> bool:
    """True if no critical/error findings relate to primary/schema integrity."""
    for f in report.findings:
        if f.area in (FindingArea.PRIMARY, FindingArea.SCHEMA):
            if f.severity in (FindingSeverity.ERROR, FindingSeverity.CRITICAL):
                return False
    # Also must have at least one INFO finding for primary (meaning we
    # actually inspected it successfully).
    return any(
        f.area == FindingArea.PRIMARY and f.severity == FindingSeverity.INFO
        for f in report.findings
    )


def _primary_was_recovered(report: DoctorReport) -> bool:
    """True if a recovery action was taken."""
    return any(
        f.area == FindingArea.PRIMARY and f.action_taken and "restore" in f.action_taken.lower()
        for f in report.findings
    )


def _get_backup_validity(
    paths: dict[str, Path],
) -> tuple[dict[str, Any], int, str] | None:
    """If backup is valid, return (data, store_revision, board_id).
    Otherwise None."""
    bak = paths["board_json_bak"]
    if not bak.is_file():
        return None
    data = _read_json_safe(bak)
    if data is None:
        return None
    try:
        _validate_envelope_schema(data, board_id=None)
    except Exception:
        return None
    if not _verify_payload_hash(data):
        return None
    rev = data.get("storeRevision", 0)
    bid = data.get("board", {}).get("board_id", "")
    if not isinstance(rev, int):
        return None
    return data, rev, str(bid)


def _atomic_write_simple(target: Path, data: dict[str, Any]) -> None:
    """Minimal atomic JSON write for doctor repair operations.

    Uses a temp file + os.replace in the same directory.  No fsync on
    the directory (doctor is best-effort repair, not the hot path).
    """
    target = Path(target)
    tmp_path = target.with_suffix(target.suffix + ".doctor.tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, target)


def _iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
