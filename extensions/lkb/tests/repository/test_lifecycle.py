"""Tests for lifecycle.py + migrations package.

Lifecycle (spec §7.8 – §7.11):
  LKB-LIFE-001 — lifecycle state defaults to "active" on genesis boards
  LKB-LIFE-002 — valid forward transitions succeed (active -> closed -> archived -> trashed -> purged)
  LKB-LIFE-005 — invalid transitions are rejected (e.g. active -> archived)
  LKB-LIFE-006 — reopen restores a closed board to active
  LKB-LIFE-007 — archive creates an archive copy with hash + revision
  LKB-LIFE-008 — restore returns board to active with source archive reference
  LKB-LIFE-009 — purge removes payload data but leaves tombstone
  LKB-LIFE-010 — gc_scan dry-run never modifies the filesystem
  LKB-LIFE-011 — gc_scan finds old temp files as candidates
  LKB-LIFE-016 — close with active claims rejected unless override+reason
  LKB-LIFE-017 — lifecycle transitions are persisted via execute_atomic

Migrations (spec §7.13):
  LKB-STORE-008 — v0 -> v1 migration upgrades schemaVersion and recomputes hash
  LKB-STORE-009 — migration is idempotent (already-v1 envelope is unchanged)
  LKB-STORE-025 — forward-compat: schema newer than code raises BoardSchemaTooNewError
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from lkb.commands import CommandResult
from lkb._testing import Failpoint
from lkb.board_resolver import safe_board_id
from lkb.file_lock import BoardFileLock
from lkb.graph_types import Board, BoardPolicy
from lkb.json_store import (
    BoardEnvelope,
    BoardStoreCorruptError,
    BoardTombstonedError,
    CURRENT_SCHEMA_VERSION,
    JsonBoardStore,
    set_payload_hash,
)
from lkb.lifecycle import (
    GC_SESSION_ORPHAN_AGE_SECONDS,
    GC_TEMP_AGE_SECONDS,
    GcCandidate,
    LifecycleData,
    LifecycleError,
    LifecycleTransitionDenied,
    archive_board,
    board_lifecycle_state,
    close_board,
    gc_apply,
    gc_scan,
    genesis_lifecycle,
    ordinary_write_allowed,
    ordinary_write_denial_reason,
    purge_board,
    read_archive,
    read_tombstone,
    reopen_board,
    restore_board,
    trash_board,
    transition,
)
from lkb.repository import ArchiveRef
from lkb.migrations import (
    CURRENT_SCHEMA_VERSION as MIG_CURRENT_SCHEMA,
    BoardSchemaTooNewError,
    MigrationError,
    migrate,
    migrate_board_file,
    v0_to_v1,
)
from lkb.refs import NodeRef


# ── helpers ───────────────────────────────────────────────────────────


def _make_board(board_id: str = "test-board") -> Board:
    return Board(
        board_id=board_id,
        project_uri=f"project:{board_id}",
        display_name=board_id,
        schema_version=1,
        store_revision=0,
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
        policy=BoardPolicy(),
    )


def _create_store(
    board_dir: Path,
    *,
    board_id: str = "test-board",
    home: Path | None = None,
) -> JsonBoardStore:
    board = _make_board(board_id)
    lock = BoardFileLock(board_dir)
    return JsonBoardStore.create_board(
        board_dir,
        board=board,
        lock=lock,
        home=home,
    )


def _create_session_store(root: Path, board_id: str) -> JsonBoardStore:
    board_dir = root / "boards" / safe_board_id(board_id)
    board = Board(
        board_id=board_id,
        project_uri=f"session:{board_id}",
        display_name=board_id,
        schema_version=1,
        store_revision=0,
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
        policy=BoardPolicy(),
    )
    return JsonBoardStore.create_board(
        board_dir,
        board=board,
        lock=BoardFileLock(board_dir),
        home=root,
    )


def _make_envelope(
    board_id: str = "test-board",
    *,
    state: str = "active",
) -> BoardEnvelope:
    """Build a minimal BoardEnvelope for lifecycle testing."""
    env = BoardEnvelope(
        store_format="lkb-json-v1",
        schema_version=1,
        store_revision=0,
        board={
            "board_id": board_id,
            "project_uri": f"project:{board_id}",
            "display_name": board_id,
            "schema_version": 1,
            "store_revision": 0,
            "policy": {},
        },
        lifecycle={
            "state": state,
            "scope": "project",
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
        },
    )
    set_payload_hash(env)
    return env


def _add_active_claim(env: BoardEnvelope, *, claim_id: str = "c1") -> None:
    """Add an active claim to *env* (mutates in place)."""
    task_ref = NodeRef("plan", "task", "T-001")
    owner_ref = NodeRef("plan", "agent", "agent-1")
    env.claims[claim_id] = {
        "claim_id": claim_id,
        "task_ref": task_ref.to_str(),
        "owner_ref": owner_ref.to_str(),
        "status": "active",
        "claimed_at": "2026-01-01T00:00:00.000Z",
        "claim_revision": 1,
    }


def _cmd_id(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _archive_ref(store: JsonBoardStore) -> ArchiveRef:
    envelope = store.load()
    info = envelope.lifecycle["archive_info"]
    document = read_archive(Path(info["archive_path"]), expected_board_id=envelope.board_id())
    return ArchiveRef(
        board_id=envelope.board_id(),
        archive_path=Path(info["archive_path"]),
        store_revision=int(document["sourceStoreRevision"]),
        payload_hash=str(document["payloadHash"]),
    )


# ── LKB-LIFE-001 ──────────────────────────────────────────────────────


class TestLkbLife001DefaultState:
    """Genesis boards default to lifecycle state 'active'."""

    def test_genesis_envelope_state_active(self) -> None:
        env = _make_envelope()
        assert board_lifecycle_state(env) == "active"

    def test_store_create_board_state_active(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board")
        env = store.load()
        assert board_lifecycle_state(env) == "active"

    def test_lifecycle_data_defaults(self) -> None:
        lc = LifecycleData()
        assert lc.state == "active"
        assert lc.scope == "project"
        assert lc.retention_policy == "default"


# ── LKB-LIFE-002 ──────────────────────────────────────────────────────


class TestLkbLife002ValidTransitions:
    """Valid transitions include explicit crash-recovery intermediate states."""

    def test_active_to_closed(self) -> None:
        env = _make_envelope()
        new_env = transition(env, "closed", actor="test-user")
        assert board_lifecycle_state(new_env) == "closed"
        # Original is unchanged.
        assert board_lifecycle_state(env) == "active"

    def test_closed_to_archived(self) -> None:
        env = _make_envelope(state="closed")
        archiving = transition(env, "archiving", actor="test-user")
        new_env = transition(archiving, "archived", actor="test-user")
        assert board_lifecycle_state(new_env) == "archived"

    def test_closed_to_trashed(self) -> None:
        env = _make_envelope(state="closed")
        new_env = transition(env, "trashed", actor="test-user")
        assert board_lifecycle_state(new_env) == "trashed"

    def test_archived_to_trashed(self) -> None:
        env = _make_envelope(state="archived")
        new_env = transition(env, "trashed", actor="test-user")
        assert board_lifecycle_state(new_env) == "trashed"

    def test_trashed_to_purging(self) -> None:
        env = _make_envelope(state="trashed")
        new_env = transition(env, "purging", actor="test-user")
        assert board_lifecycle_state(new_env) == "purging"

    def test_transition_records_event(self) -> None:
        env = _make_envelope()
        new_env = transition(env, "closed", actor="alice", reason="cleanup")
        events = [e for e in new_env.events if e.get("type") == "lifecycle_transition"]
        assert len(events) == 1
        ev = events[0]
        assert ev["from_state"] == "active"
        assert ev["to_state"] == "closed"
        assert ev["actor"] == "alice"
        assert ev["reason"] == "cleanup"

    def test_idempotent_same_state(self) -> None:
        env = _make_envelope(state="closed")
        new_env = transition(env, "closed", actor="test-user")
        # Already in target state — returns the same object (no-op).
        assert new_env is env

    def test_timestamp_updated(self) -> None:
        env = _make_envelope()
        new_env = transition(env, "closed", actor="test-user")
        lc = LifecycleData.from_dict(new_env.lifecycle)
        assert lc.closed_at != ""
        assert lc.updated_at != ""


# ── LKB-LIFE-005 ──────────────────────────────────────────────────────


class TestLkbLife005InvalidTransitions:
    """Invalid state transitions are rejected."""

    def test_active_to_archived_direct_rejected(self) -> None:
        env = _make_envelope()
        with pytest.raises(LifecycleTransitionDenied) as exc_info:
            transition(env, "archived", actor="test-user")
        assert exc_info.value.from_state == "active"
        assert exc_info.value.to_state == "archived"

    def test_active_to_trashed_direct_rejected(self) -> None:
        env = _make_envelope()
        with pytest.raises(LifecycleTransitionDenied):
            transition(env, "trashed", actor="test-user")

    def test_active_to_purged_direct_rejected(self) -> None:
        env = _make_envelope()
        with pytest.raises(LifecycleTransitionDenied):
            transition(env, "purged", actor="test-user")

    def test_purged_no_outgoing_transitions(self) -> None:
        env = _make_envelope(state="purged")
        with pytest.raises(LifecycleTransitionDenied):
            transition(env, "active", actor="test-user")
        with pytest.raises(LifecycleTransitionDenied):
            transition(env, "closed", actor="test-user")

    def test_invalid_target_state_rejected(self) -> None:
        env = _make_envelope()
        with pytest.raises(LifecycleTransitionDenied, match="invalid target state"):
            transition(env, "bogus", actor="test-user")

    def test_board_id_in_error(self) -> None:
        env = _make_envelope("board-X")
        with pytest.raises(LifecycleTransitionDenied) as exc_info:
            transition(env, "archived", actor="test-user")
        assert exc_info.value.board_id == "board-X"


# ── LKB-LIFE-006 ──────────────────────────────────────────────────────


class TestLkbLife006Reopen:
    """Reopen restores a closed board to active."""

    def test_closed_to_active(self) -> None:
        env = _make_envelope(state="closed")
        new_env = transition(env, "active", actor="test-user")
        assert board_lifecycle_state(new_env) == "active"
        lc = LifecycleData.from_dict(new_env.lifecycle)
        assert lc.closed_at == ""

    def test_trashed_to_active(self) -> None:
        env = _make_envelope(state="trashed")
        new_env = transition(env, "active", actor="test-user")
        assert board_lifecycle_state(new_env) == "active"

    def test_archived_to_active_restore(self) -> None:
        env = _make_envelope(state="archived")
        new_env = transition(env, "active", actor="test-user")
        assert board_lifecycle_state(new_env) == "active"
        lc = LifecycleData.from_dict(new_env.lifecycle)
        assert lc.archived_at == ""


# ── LKB-LIFE-007 / LKB-LIFE-008 ──────────────────────────────────────


class TestLkbLife007ArchiveRestore:
    """Archive creates archive copy; restore returns to active."""

    def test_archive_board_persists_transition(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        # First close the board (archive requires closed state).
        close_board(
            store,
            "test-board",
            actor="test-user",
            command_id=_cmd_id("close"),
            request_hash="hash-close",
        )

        # Then archive.
        result = archive_board(
            store,
            "test-board",
            actor="test-user",
            command_id=_cmd_id("archive"),
            request_hash="hash-archive",
            reason="project completed",
        )
        assert result.committed

        env = store.load()
        assert board_lifecycle_state(env) == "archived"

    def test_archive_creates_archive_file(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        close_board(
            store,
            "test-board",
            actor="test-user",
            command_id=_cmd_id("close"),
            request_hash="hash-close",
        )
        archive_board(
            store,
            "test-board",
            actor="test-user",
            command_id=_cmd_id("archive"),
            request_hash="hash-archive",
        )

        # Archive directory should exist.
        archive_dir = tmp_lkb_root / "archives"
        assert archive_dir.is_dir()
        # There should be one archive subdirectory.
        archives = list(archive_dir.iterdir())
        assert len(archives) >= 1

    def test_restore_board_returns_to_active(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        # Close -> archive -> restore.
        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        archive_board(store, "test-board", actor="u", command_id=_cmd_id("a"), request_hash="h2")
        archive_ref = _archive_ref(store)
        result = restore_board(
            store,
            "test-board",
            archive_ref=archive_ref,
            actor="u",
            command_id=_cmd_id("r"),
            request_hash="h3",
            reason="need it back",
        )
        assert result.committed

        env = store.load()
        assert board_lifecycle_state(env) == "active"

    def test_restore_records_source_archive(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        archive_board(store, "test-board", actor="u", command_id=_cmd_id("a"), request_hash="h2")
        restore_board(
            store,
            "test-board",
            archive_ref=_archive_ref(store),
            actor="u",
            command_id=_cmd_id("r"),
            request_hash="h3",
        )

        env = store.load()
        restore_info = env.lifecycle.get("restore_info")
        assert restore_info is not None
        assert restore_info.get("restored_by") == "u"


# ── LKB-LIFE-009 ──────────────────────────────────────────────────────


class TestLkbLife009Purge:
    """Purge removes payload data but leaves tombstone."""

    def test_purge_requires_confirm(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        # Close -> trash -> purge.
        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        trash_board(store, "test-board", actor="u", command_id=_cmd_id("t"), request_hash="h2")

        with pytest.raises(ValueError, match="confirm"):
            purge_board(
                store,
                "test-board",
                actor="u",
                command_id=_cmd_id("p"),
                request_hash="h3",
                reason="cleanup",
                confirm="wrong-id",
            )

    def test_purge_requires_reason(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        trash_board(store, "test-board", actor="u", command_id=_cmd_id("t"), request_hash="h2")

        with pytest.raises(ValueError, match="reason"):
            purge_board(
                store,
                "test-board",
                actor="u",
                command_id=_cmd_id("p"),
                request_hash="h3",
                reason="",
                confirm="test-board",
            )

    def test_purge_clears_payload(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        # Add a node so there's payload to clear.
        def add_node(env: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
            ref = NodeRef("plan", "task", "T-001")
            env.nodes["T-001"] = {
                "ref": ref.to_str(),
                "title": "test task",
                "state": "pending",
                "revision": 1,
                "payload": {},
            }
            env.graphs["plan"] = {
                "graph_id": "plan",
                "board_id": "test-board",
                "graph_kind": "plan",
                "revision": 1,
            }
            result = CommandResult(decision="committed", command_id="add")
            return env, result

        store.execute_atomic(
            "test-board",
            "cmd-add",
            "hash-add",
            None,
            add_node,
            actor="u",
        )

        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        trash_board(store, "test-board", actor="u", command_id=_cmd_id("t"), request_hash="h2")
        result = purge_board(
            store,
            "test-board",
            actor="u",
            command_id=_cmd_id("p"),
            request_hash="h3",
            reason="gdpr request",
            confirm="test-board",
            authorized=True,
        )
        assert result.committed

        with pytest.raises(BoardTombstonedError):
            store.load()
        assert not (board_dir / "board.json").exists()
        marker = next((tmp_lkb_root / "tombstones").glob("*.json"))
        tombstone = read_tombstone(marker, expected_board_id="test-board")
        assert tombstone["purgedBy"] == "u"
        assert tombstone["reason"] == "gdpr request"
        assert (board_dir / ".lock").is_file()


# ── LKB-LIFE-010 / LKB-LIFE-011 ──────────────────────────────────────


class TestLkbLife010GcScan:
    """gc_scan dry-run never modifies; finds old temp files."""

    def test_dry_run_does_not_delete(self, tmp_lkb_root: Path) -> None:
        # Create a temp file that's old enough to be a candidate.
        tmp_dir = tmp_lkb_root / "boards" / "test-board" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        old_tmp = tmp_dir / ".board.json.old-file.tmp"
        old_tmp.write_text("stale", encoding="utf-8")

        # Set mtime to 48h ago.
        old_time = time.time() - (GC_TEMP_AGE_SECONDS + 3600)
        os.utime(old_tmp, (old_time, old_time))

        before_size = old_tmp.stat().st_size
        candidates = gc_scan(tmp_lkb_root, dry_run=True)

        # File still exists after dry-run.
        assert old_tmp.is_file()
        assert old_tmp.stat().st_size == before_size
        # But it was reported as a candidate.
        assert any(c.path == old_tmp for c in candidates)

    def test_finds_old_temp_files(self, tmp_lkb_root: Path) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "board-a" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Old temp file (should be found).
        old_tmp = tmp_dir / ".board.json.old.tmp"
        old_tmp.write_text("old", encoding="utf-8")
        old_time = time.time() - (GC_TEMP_AGE_SECONDS + 100)
        os.utime(old_tmp, (old_time, old_time))

        # Recent temp file (should NOT be found).
        new_tmp = tmp_dir / ".board.json.new.tmp"
        new_tmp.write_text("new", encoding="utf-8")
        new_time = time.time() - 60  # 1 minute ago
        os.utime(new_tmp, (new_time, new_time))

        candidates = gc_scan(tmp_lkb_root, dry_run=True)
        temp_candidates = [c for c in candidates if c.kind == "temp"]
        assert any(c.path == old_tmp for c in temp_candidates)
        assert not any(c.path == new_tmp for c in temp_candidates)

    def test_empty_root_returns_empty(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "lkb-empty"
        empty_root.mkdir()
        candidates = gc_scan(empty_root, dry_run=True)
        assert candidates == []

    def test_candidates_sorted_by_age_desc(self, tmp_lkb_root: Path) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "board-b" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # Create two temp files with different ages.
        for i, hours in enumerate([48, 72]):
            f = tmp_dir / f".board.json.file-{i}.tmp"
            f.write_text("x", encoding="utf-8")
            t = time.time() - hours * 3600
            os.utime(f, (t, t))

        candidates = gc_scan(tmp_lkb_root, dry_run=True)
        temp_cands = [c for c in candidates if c.kind == "temp"]
        assert len(temp_cands) >= 2
        for i in range(len(temp_cands) - 1):
            assert temp_cands[i].age_seconds >= temp_cands[i + 1].age_seconds

    def test_quarantine_candidates(self, tmp_lkb_root: Path) -> None:
        q_dir = tmp_lkb_root / "boards" / "board-c" / "quarantine"
        q_dir.mkdir(parents=True, exist_ok=True)

        q_file = q_dir / "corrupt.1234.primary-corrupt"
        q_file.write_text("broken", encoding="utf-8")
        # 35 days old (past the 30-day threshold).
        old_time = time.time() - 35 * 24 * 3600
        os.utime(q_file, (old_time, old_time))

        candidates = gc_scan(tmp_lkb_root, dry_run=True)
        q_cands = [c for c in candidates if c.kind == "quarantine"]
        assert any(c.path == q_file for c in q_cands)

    def test_gc_candidate_attributes(self, tmp_lkb_root: Path) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "board-d" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        f = tmp_dir / ".board.json.stale.tmp"
        f.write_bytes(b"x" * 100)
        old_time = time.time() - (GC_TEMP_AGE_SECONDS + 1000)
        os.utime(f, (old_time, old_time))

        candidates = gc_scan(tmp_lkb_root, dry_run=True)
        temp_cands = [c for c in candidates if c.path == f]
        assert len(temp_cands) == 1
        c = temp_cands[0]
        assert c.kind == "temp"
        assert c.age_seconds > 0
        assert c.size_bytes == 100
        assert "temp" in c.reason


# ── LKB-LIFE-016 ──────────────────────────────────────────────────────


class TestLkbLife016ActiveClaimsGuard:
    """Close with active claims rejected unless override + reason (LKB-LIFE-016)."""

    def test_close_with_active_claims_rejected(self) -> None:
        env = _make_envelope()
        _add_active_claim(env)
        with pytest.raises(LifecycleTransitionDenied, match="active claims"):
            transition(env, "closed", actor="test-user")

    def test_close_with_override_no_reason_rejected(self) -> None:
        env = _make_envelope()
        _add_active_claim(env)
        with pytest.raises(LifecycleTransitionDenied, match="active claims"):
            transition(env, "closed", actor="test-user", override_active_claims=True)

    def test_close_with_override_and_reason_allowed(self) -> None:
        env = _make_envelope()
        _add_active_claim(env)
        new_env = transition(
            env,
            "closed",
            actor="test-user",
            reason="emergency shutdown",
            override_active_claims=True,
        )
        assert board_lifecycle_state(new_env) == "closed"
        # Verify the override is recorded in the event.
        events = [e for e in new_env.events if e.get("type") == "lifecycle_transition"]
        assert events
        assert events[-1].get("override_active_claims") is True

    def test_close_no_claims_succeeds(self) -> None:
        env = _make_envelope()
        new_env = transition(env, "closed", actor="test-user")
        assert board_lifecycle_state(new_env) == "closed"


# ── LKB-LIFE-017 ──────────────────────────────────────────────────────


class TestLkbLife017PersistedTransitions:
    """Lifecycle transitions are persisted via execute_atomic."""

    def test_close_board_persists(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        result = close_board(
            store,
            "test-board",
            actor="test-user",
            command_id="cmd-close-1",
            request_hash="hash-close-1",
            reason="cleanup",
        )
        assert result.committed

        # Re-load and verify.
        env = store.load()
        assert board_lifecycle_state(env) == "closed"
        assert env.store_revision == 1  # genesis (0) + 1 transition

    def test_close_is_idempotent_via_command_id(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        cmd_id = _cmd_id("close")
        close_board(
            store,
            "test-board",
            actor="test-user",
            command_id=cmd_id,
            request_hash="hash-close",
        )
        # Same command_id + same hash — should return cached result.
        result = close_board(
            store,
            "test-board",
            actor="test-user",
            command_id=cmd_id,
            request_hash="hash-close",
        )
        assert result.committed
        # store_revision should still be 1 (no new revision).
        env = store.load()
        assert env.store_revision == 1

    def test_full_lifecycle_chain_persisted(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        # active -> closed
        close_board(store, "test-board", actor="u", command_id=_cmd_id("c1"), request_hash="h1")
        # closed -> archived
        archive_board(store, "test-board", actor="u", command_id=_cmd_id("a1"), request_hash="h2")
        # archived -> trashed (via trash_board)
        trash_board(store, "test-board", actor="u", command_id=_cmd_id("t1"), request_hash="h3")
        # trashed -> purged
        purge_board(
            store,
            "test-board",
            actor="u",
            command_id=_cmd_id("p1"),
            request_hash="h4",
            reason="end of life",
            confirm="test-board",
            authorized=True,
        )

        with pytest.raises(BoardTombstonedError):
            store.load()
        assert not (board_dir / "board.json").exists()
        assert list((tmp_lkb_root / "tombstones").glob("*.json"))

    def test_reopen_after_close(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)

        close_board(store, "test-board", actor="u", command_id=_cmd_id("c"), request_hash="h1")
        result = reopen_board(
            store,
            "test-board",
            actor="u",
            command_id=_cmd_id("r"),
            request_hash="h2",
            reason="reconsidered",
        )
        assert result.committed
        env = store.load()
        assert board_lifecycle_state(env) == "active"


# ── LKB-STORE-008 ────────────────────────────────────────────────────


class TestLkbStore008V0ToV1Migration:
    """v0 -> v1 migration upgrades schemaVersion and recomputes hash."""

    def test_migration_adds_schema_version(self) -> None:
        v0_env = {
            "storeFormat": "lkb-json-v1",
            "storeRevision": 0,
            "board": {"board_id": "test-board"},
        }
        result, applied = migrate(v0_env, target_schema=1)
        assert result["schemaVersion"] == 1
        assert applied == [1]

    def test_migration_sets_integrity_hash(self) -> None:
        v0_env = {
            "storeFormat": "lkb-json-v1",
            "storeRevision": 0,
            "board": {"board_id": "test-board"},
        }
        result, _ = migrate(v0_env, target_schema=1)
        integrity = result.get("integrity")
        assert isinstance(integrity, dict)
        assert integrity.get("algorithm") == "sha256"
        assert integrity.get("payloadHash", "").startswith("sha256:")

    def test_migration_sets_lifecycle_default(self) -> None:
        v0_env = {
            "board": {"board_id": "test-board"},
        }
        result, _ = migrate(v0_env, target_schema=1)
        lifecycle = result.get("lifecycle")
        assert isinstance(lifecycle, dict)
        assert lifecycle.get("state") == "active"

    def test_migration_preserves_board_data(self) -> None:
        v0_env = {
            "board": {
                "board_id": "my-board",
                "display_name": "My Board",
                "project_uri": "project:my-proj",
            },
            "graphs": {"plan": {"graph_id": "plan", "graph_kind": "plan"}},
        }
        result, _ = migrate(v0_env, target_schema=1)
        assert result["board"]["board_id"] == "my-board"
        assert result["board"]["display_name"] == "My Board"
        assert "plan" in result["graphs"]


# ── LKB-STORE-009 ────────────────────────────────────────────────────


class TestLkbStore009MigrationIdempotent:
    """Migration is idempotent — already-v1 envelope is unchanged."""

    def test_v1_envelope_no_op(self) -> None:
        v1_env = {
            "storeFormat": "lkb-json-v1",
            "schemaVersion": 1,
            "storeRevision": 3,
            "board": {"board_id": "test-board"},
            "graphs": {},
            "nodes": {},
            "edges": {},
            "claims": {},
            "assertions": {},
            "evidence": {},
            "validationRuns": {},
            "processedCommands": {},
            "events": [],
            "historySegments": [],
            "lifecycle": {"state": "active"},
            "integrity": {"algorithm": "sha256", "payloadHash": "sha256:abc123"},
        }
        # Pass the same dict object — migrate should return it unchanged.
        result, applied = migrate(v1_env, target_schema=1)
        assert applied == []
        # The envelope should be returned as-is (same dict reference)
        # when no migration is needed.
        assert result is v1_env
        assert result["schemaVersion"] == 1

    def test_v0_to_v1_function_direct_idempotent(self) -> None:
        v1_env = {
            "schemaVersion": 1,
            "board": {"board_id": "test"},
        }
        result = v0_to_v1(dict(v1_env))
        # Already v1 — returns unchanged.
        assert result["schemaVersion"] == 1


# ── LKB-STORE-025 ────────────────────────────────────────────────────


class TestLkbStore025ForwardCompat:
    """Forward-compat: schema newer than code raises BoardSchemaTooNewError."""

    def test_newer_schema_raises(self) -> None:
        v5_env = {
            "schemaVersion": 5,
            "board": {"board_id": "future-board"},
        }
        with pytest.raises(BoardSchemaTooNewError) as exc_info:
            migrate(v5_env, target_schema=1)
        assert exc_info.value.board_id == "future-board"
        assert exc_info.value.on_disk_version == 5
        assert exc_info.value.supported_version == 1

    def test_current_schema_constant_consistent(self) -> None:
        """The migrations CURRENT_SCHEMA_VERSION matches json_store's."""
        assert MIG_CURRENT_SCHEMA == CURRENT_SCHEMA_VERSION

    def test_exact_match_no_error(self) -> None:
        v1_env = {
            "schemaVersion": 1,
            "board": {"board_id": "ok-board"},
        }
        result, applied = migrate(v1_env, target_schema=1)
        assert applied == []
        assert result["schemaVersion"] == 1

    def test_migration_error_on_missing_chain(self) -> None:
        """If the migration chain has a gap, MigrationError is raised."""
        # Trying to migrate to a version beyond what's registered.
        # With only v0->v1 registered, target=3 should fail.
        v0_env = {
            "board": {"board_id": "test"},
        }
        with pytest.raises(MigrationError, match="No migration registered"):
            migrate(v0_env, target_schema=3)


class TestPhase2LifecycleBoundaries:
    def test_genesis_lifecycle_has_every_required_field(self) -> None:
        lifecycle = genesis_lifecycle(
            scope="project",
            created_at="2026-01-01T00:00:00Z",
            origin_project_uri="project:/repo",
        )
        assert set(lifecycle) == {
            "state",
            "scope",
            "created_at",
            "updated_at",
            "closed_at",
            "archived_at",
            "retention_policy",
            "origin_project_uri",
        }

    @pytest.mark.parametrize(
        ("state", "allowed"),
        [
            ("active", True),
            ("closed", False),
            ("archiving", False),
            ("archived", False),
            ("trashed", False),
            ("purging", False),
        ],
    )
    def test_ordinary_write_gate_is_pure(self, state: str, allowed: bool) -> None:
        env = _make_envelope(state=state)
        before = env.to_dict()
        assert ordinary_write_allowed(env) is allowed
        assert (ordinary_write_denial_reason(env) is None) is allowed
        assert env.to_dict() == before

    def test_archive_document_links_hash_revision_and_source(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)
        close_board(store, "test-board", actor="u", command_id="close", request_hash="hc")
        archive_board(store, "test-board", actor="u", command_id="archive", request_hash="ha")
        archived = store.load()
        info = archived.lifecycle["archive_info"]
        archive_path = Path(info["archive_path"])
        document = json.loads(archive_path.read_text(encoding="utf-8"))
        assert document["boardId"] == "test-board"
        assert document["sourceStoreRevision"] == info["source_store_revision"]
        assert document["payloadHash"] == info["archive_hash"]
        assert archive_path.is_file()

    def test_corrupt_archive_refuses_restore_and_archive_is_retained(
        self, tmp_lkb_root: Path
    ) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)
        close_board(store, "test-board", actor="u", command_id="close", request_hash="hc")
        archive_board(store, "test-board", actor="u", command_id="archive", request_hash="ha")
        archive_ref = _archive_ref(store)
        archive_path = Path(store.load().lifecycle["archive_info"]["archive_path"])
        document = json.loads(archive_path.read_text(encoding="utf-8"))
        document["sourceStoreRevision"] += 1
        archive_path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(Exception, match="archive"):
            restore_board(
                store,
                "test-board",
                archive_ref=archive_ref,
                actor="u",
                command_id="restore",
                request_hash="hr",
            )
        assert archive_path.is_file()
        assert board_lifecycle_state(store.load()) == "archived"

    def test_purge_requires_permission(self, tmp_lkb_root: Path) -> None:
        board_dir = tmp_lkb_root / "boards" / "test-board"
        store = _create_store(board_dir, board_id="test-board", home=tmp_lkb_root)
        close_board(store, "test-board", actor="u", command_id="close", request_hash="hc")
        trash_board(store, "test-board", actor="u", command_id="trash", request_hash="ht")
        with pytest.raises(PermissionError):
            purge_board(
                store,
                "test-board",
                actor="u",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="test-board",
                authorized=False,
            )

    def test_active_claim_blocks_archive_and_purge(self) -> None:
        closed = _make_envelope(state="closed")
        _add_active_claim(closed)
        with pytest.raises(LifecycleTransitionDenied):
            transition(closed, "archiving", actor="u")
        trashed = _make_envelope(state="trashed")
        _add_active_claim(trashed)
        with pytest.raises(LifecycleTransitionDenied):
            transition(trashed, "purging", actor="u")


class TestPhase2GcBoundaries:
    def test_expired_session_orphan_is_discovered_and_deleted_when_requested(
        self, tmp_lkb_root: Path
    ) -> None:
        store = _create_session_store(tmp_lkb_root, "session-board")
        board_dir = Path(store._board_dir)
        board_json = board_dir / "board.json"
        now = 4_000_000.0
        old = now - GC_SESSION_ORPHAN_AGE_SECONDS - 1
        os.utime(board_json, (old, old))
        dry_run = gc_scan(tmp_lkb_root, dry_run=True, now=now)
        assert any(item.kind == "session_orphan" for item in dry_run)
        assert board_json.is_file()
        gc_scan(tmp_lkb_root, dry_run=False, now=now)
        assert not board_json.exists()
        assert (board_dir / ".lock").is_file()

    def test_non_dry_run_deletes_only_named_atomic_temp(self, tmp_lkb_root: Path) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "board-a" / ".tmp"
        tmp_dir.mkdir(parents=True)
        orphan = tmp_dir / ".board.json.abc.tmp"
        suspicious = tmp_dir / "notes.txt"
        orphan.write_text("{}", encoding="utf-8")
        suspicious.write_text("keep", encoding="utf-8")
        now = 2_000_000.0
        old = now - GC_TEMP_AGE_SECONDS - 1
        os.utime(orphan, (old, old))
        os.utime(suspicious, (old, old))
        gc_scan(tmp_lkb_root, dry_run=False, now=now)
        assert not orphan.exists()
        assert not suspicious.exists()
        assert (tmp_dir.parent / "quarantine" / "notes.txt").is_file()
        assert (tmp_dir.parent / ".lock").is_file()

    def test_symlink_is_reported_and_never_followed(self, tmp_lkb_root: Path) -> None:
        target = tmp_lkb_root / "outside"
        target.mkdir()
        marker = target / "marker"
        marker.write_text("keep", encoding="utf-8")
        boards = tmp_lkb_root / "boards"
        boards.mkdir()
        link = boards / "linked-board"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("symlink unavailable")
        candidates = gc_scan(tmp_lkb_root, dry_run=False, now=2_000_000.0)
        assert any(item.kind == "unsafe_path" and item.path == link for item in candidates)
        assert marker.is_file()

    def test_expired_quarantine_is_report_only(self, tmp_lkb_root: Path) -> None:
        quarantine = tmp_lkb_root / "boards" / "b" / "quarantine"
        quarantine.mkdir(parents=True)
        item = quarantine / "candidate"
        item.write_text("keep", encoding="utf-8")
        now = 3_000_000.0
        old = now - 31 * 24 * 3600
        os.utime(item, (old, old))
        candidates = gc_scan(tmp_lkb_root, dry_run=False, now=now)
        candidate = next(value for value in candidates if value.path == item)
        assert candidate.action == "report"
        assert item.is_file()


class TestPhase2MigrationOrchestrator:
    def test_v0_file_migrates_atomically_and_preserves_unknown_fields(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "board.json"
        original = {
            "board": {
                "board_id": "b",
                "project_uri": "project:/repo",
                "custom": {"retained": True},
            },
            "events": [{"legacy": 1}],
            "unknownTopLevel": {"x": 2},
        }
        path.write_text(json.dumps(original), encoding="utf-8")
        outcome = migrate_board_file(path, expected_board_id="b")
        migrated = json.loads(path.read_text(encoding="utf-8"))
        assert migrated["schemaVersion"] == 1
        assert migrated["board"]["custom"] == {"retained": True}
        assert migrated["board"]["compatibility_metadata"]["legacy_top_level"][
            "unknownTopLevel"
        ] == {"x": 2}
        assert outcome.backup_path.is_file()
        assert json.loads(outcome.backup_path.read_text(encoding="utf-8")) == original

    def test_migration_failpoint_preserves_backup_and_diagnostic_candidate(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "board.json"
        original = {"board": {"board_id": "b"}}
        path.write_text(json.dumps(original), encoding="utf-8")
        failpoint = Failpoint()
        failpoint.register("after_fsync_before_replace", OSError("injected"))
        with pytest.raises(MigrationError, match="candidate"):
            migrate_board_file(path, expected_board_id="b", failpoint=failpoint)
        assert json.loads(path.read_text(encoding="utf-8")) == original
        backups = list((tmp_path / "migration-backups").glob("*.json"))
        candidates = list((tmp_path / "quarantine").glob("*.migration-*.json"))
        diagnostics = list((tmp_path / "quarantine").glob("*.error.json"))
        assert backups and candidates and diagnostics

    @pytest.mark.parametrize(
        "stage",
        [
            "migration_before_backup",
            "migration_after_backup",
            "migration_after_transform",
            "migration_after_validate",
            "migration_before_publish",
            "migration_after_publish",
        ],
    )
    def test_each_migration_stage_leaves_one_diagnostic(
        self, tmp_path: Path, stage: str
    ) -> None:
        path = tmp_path / "board.json"
        original = {"board": {"board_id": "b"}}
        path.write_text(json.dumps(original), encoding="utf-8")
        failpoint = Failpoint()
        failpoint.register(stage, RuntimeError(stage))
        with pytest.raises(MigrationError, match=stage):
            migrate_board_file(path, expected_board_id="b", failpoint=failpoint)
        diagnostics = list((tmp_path / "quarantine").glob("*.error.json"))
        candidates = list((tmp_path / "quarantine").glob("*.candidate.json"))
        assert len(diagnostics) == 1
        assert len(candidates) == 1
        diagnostic = json.loads(diagnostics[0].read_text(encoding="utf-8"))
        assert diagnostic["error"] == stage
        assert json.loads(path.read_text(encoding="utf-8")).get("schemaVersion", 0) in {
            0,
            1,
        }


class TestArchiveCrashRecoveryAndCas:
    def test_failure_after_prepare_resumes_same_operation(self, tmp_lkb_root: Path) -> None:
        store = _create_store(
            tmp_lkb_root / "boards" / "archive-prepare",
            board_id="archive-prepare",
            home=tmp_lkb_root,
        )
        close_board(
            store, "archive-prepare", actor="u", command_id="close", request_hash="hc"
        )
        failpoint = Failpoint()
        failpoint.register("archive_after_prepare", RuntimeError("stop-after-prepare"))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match="stop-after-prepare"):
            archive_board(
                store,
                "archive-prepare",
                actor="original-actor",
                command_id="archive",
                request_hash="ha",
                reason="original reason",
            )
        prepared = store.load()
        assert board_lifecycle_state(prepared) == "archiving"
        operation_id = prepared.lifecycle["archive_operation"]["archive_id"]
        failpoint.unregister("archive_after_prepare")
        result = archive_board(
            store,
            "archive-prepare",
            actor="recovery-actor",
            command_id="archive-recovery",
            request_hash="ha-recovery",
            reason="replacement reason",
        )
        assert result.committed
        archive_info = store.load().lifecycle["archive_info"]
        assert archive_info["archive_id"] == operation_id
        assert archive_info["archived_by"] == "original-actor"
        assert archive_info["reason"] == "original reason"
        wrapper = read_archive(
            Path(archive_info["archive_path"]), expected_board_id="archive-prepare"
        )
        assert wrapper["createdBy"] == "original-actor"
        assert wrapper["reason"] == "original reason"

    def test_failure_after_publish_keeps_immutable_archive_and_resumes(
        self, tmp_lkb_root: Path
    ) -> None:
        store = _create_store(
            tmp_lkb_root / "boards" / "archive-publish",
            board_id="archive-publish",
            home=tmp_lkb_root,
        )
        close_board(
            store, "archive-publish", actor="u", command_id="close", request_hash="hc"
        )
        failpoint = Failpoint()
        failpoint.register("archive_after_publish", RuntimeError("stop-after-publish"))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match="stop-after-publish"):
            archive_board(
                store,
                "archive-publish",
                actor="u",
                command_id="archive",
                request_hash="ha",
            )
        assert board_lifecycle_state(store.load()) == "archiving"
        archive_files = list((tmp_lkb_root / "archives").rglob("*.json"))
        assert len(archive_files) == 1
        original_bytes = archive_files[0].read_bytes()
        failpoint.unregister("archive_after_publish")
        archive_board(
            store,
            "archive-publish",
            actor="u",
            command_id="archive",
            request_hash="ha",
        )
        assert archive_files[0].read_bytes() == original_bytes
        assert board_lifecycle_state(store.load()) == "archived"

    def test_archive_cas_rejects_concurrent_lifecycle_change(
        self, tmp_lkb_root: Path
    ) -> None:
        store = _create_store(
            tmp_lkb_root / "boards" / "archive-race",
            board_id="archive-race",
            home=tmp_lkb_root,
        )
        close_board(store, "archive-race", actor="u", command_id="close", request_hash="hc")
        failpoint = Failpoint()

        def change_state(_name: str) -> None:
            def mutate(env: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
                candidate = transition(env, "closed", actor="racer", reason="race")
                candidate.lifecycle.pop("archive_operation", None)
                return candidate, CommandResult(decision="committed", command_id="race")

            store.execute_atomic(
                "archive-race",
                "race",
                "race-hash",
                None,
                mutate,
                actor="racer",
                lifecycle_operation=True,
            )

        failpoint.register("archive_after_publish", change_state)
        store._failpoint = failpoint
        with pytest.raises(LifecycleError, match="CAS"):
            archive_board(
                store,
                "archive-race",
                actor="u",
                command_id="archive",
                request_hash="ha",
            )
        assert board_lifecycle_state(store.load()) == "closed"
        assert list((tmp_lkb_root / "archives").rglob("*.json"))

    def test_repeated_archive_does_not_overwrite_or_increment(
        self, tmp_lkb_root: Path
    ) -> None:
        store = _create_store(
            tmp_lkb_root / "boards" / "archive-repeat",
            board_id="archive-repeat",
            home=tmp_lkb_root,
        )
        close_board(
            store, "archive-repeat", actor="u", command_id="close", request_hash="hc"
        )
        archive_board(
            store,
            "archive-repeat",
            actor="u",
            command_id="archive-1",
            request_hash="ha1",
        )
        revision = store.load().store_revision
        files = list((tmp_lkb_root / "archives").rglob("*.json"))
        archive_board(
            store,
            "archive-repeat",
            actor="u",
            command_id="archive-2",
            request_hash="ha2",
        )
        assert store.load().store_revision == revision
        assert list((tmp_lkb_root / "archives").rglob("*.json")) == files


class TestPurgeTwoPhaseRecovery:
    def _trashed_store(self, root: Path, board_id: str) -> JsonBoardStore:
        store = _create_store(
            root / "boards" / board_id, board_id=board_id, home=root
        )
        close_board(store, board_id, actor="u", command_id="close", request_hash="hc")
        trash_board(store, board_id, actor="u", command_id="trash", request_hash="ht")
        return store

    def test_failure_after_purging_resumes_without_reporting_success(
        self, tmp_lkb_root: Path
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-prepare")
        failpoint = Failpoint()
        failpoint.register("purge_after_prepare", RuntimeError("stop-after-purging"))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match="stop-after-purging"):
            purge_board(
                store,
                "purge-prepare",
                actor="original-admin",
                command_id="purge",
                request_hash="hp",
                reason="original cleanup",
                confirm="purge-prepare",
                authorized=True,
            )
        assert board_lifecycle_state(store.load()) == "purging"
        assert not list((tmp_lkb_root / "tombstones").glob("*.json"))
        failpoint.unregister("purge_after_prepare")
        assert purge_board(
            store,
            "purge-prepare",
            actor="recovery-admin",
            command_id="purge-recovery",
            request_hash="hp-recovery",
            reason="replacement cleanup",
            confirm="purge-prepare",
            authorized=True,
        ).committed
        assert not (tmp_lkb_root / "boards" / "purge-prepare" / "board.json").exists()
        marker = next((tmp_lkb_root / "tombstones").glob("*.json"))
        tombstone = read_tombstone(marker, expected_board_id="purge-prepare")
        assert tombstone["purgedBy"] == "original-admin"
        assert tombstone["reason"] == "original cleanup"

    @pytest.mark.parametrize("stage", ["purge_after_pending", "purge_before_delete"])
    def test_failure_before_managed_deletion_is_reentrant(
        self, tmp_lkb_root: Path, stage: str
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, f"purge-{stage}")
        board_id = f"purge-{stage}"
        failpoint = Failpoint()
        failpoint.register(stage, RuntimeError(stage))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match=stage):
            purge_board(
                store,
                board_id,
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm=board_id,
                authorized=True,
            )
        assert board_lifecycle_state(store.load()) == "purging"
        assert not list((tmp_lkb_root / "tombstones").glob("*.json"))

        failpoint.unregister(stage)
        assert purge_board(
            store,
            board_id,
            actor="recovery-admin",
            command_id="purge-recovery",
            request_hash="hp-recovery",
            reason="replacement cleanup",
            confirm=board_id,
            authorized=True,
        ).committed

    @pytest.mark.parametrize("stage", ["purge_after_delete", "purge_before_tombstone"])
    def test_failure_after_managed_deletion_publishes_tombstone_on_retry(
        self, tmp_lkb_root: Path, stage: str
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-delete")
        failpoint = Failpoint()
        failpoint.register(stage, RuntimeError(stage))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match=stage):
            purge_board(
                store,
                "purge-delete",
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="purge-delete",
                authorized=True,
            )
        assert not (tmp_lkb_root / "boards" / "purge-delete" / "board.json").exists()
        assert not list((tmp_lkb_root / "tombstones").glob("*.json"))
        assert list((tmp_lkb_root / "tombstones").glob("*.purge-pending"))

        failpoint.unregister(stage)
        result = purge_board(
            store,
            "purge-delete",
            actor="recovery-admin",
            command_id="purge-recovery",
            request_hash="hp-recovery",
            reason="replacement cleanup",
            confirm="purge-delete",
            authorized=True,
        )
        assert result.committed
        marker = next((tmp_lkb_root / "tombstones").glob("*.json"))
        tombstone = read_tombstone(marker, expected_board_id="purge-delete")
        assert tombstone["purgedBy"] == "admin"
        assert tombstone["reason"] == "cleanup"
        assert not list((tmp_lkb_root / "tombstones").glob("*.purge-pending"))

    def test_failure_after_tombstone_resumes_completed_purge(
        self, tmp_lkb_root: Path
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-tombstone")
        failpoint = Failpoint()
        failpoint.register("purge_after_tombstone", RuntimeError("stop-after-tombstone"))
        store._failpoint = failpoint
        with pytest.raises(RuntimeError, match="stop-after-tombstone"):
            purge_board(
                store,
                "purge-tombstone",
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="purge-tombstone",
                authorized=True,
            )
        assert not (tmp_lkb_root / "boards" / "purge-tombstone" / "board.json").exists()
        assert list((tmp_lkb_root / "tombstones").glob("*.json"))
        failpoint.unregister("purge_after_tombstone")
        result = purge_board(
            store,
            "purge-tombstone",
            actor="admin",
            command_id="purge",
            request_hash="hp",
            reason="cleanup",
            confirm="purge-tombstone",
            authorized=True,
        )
        assert result.committed
        assert not (tmp_lkb_root / "boards" / "purge-tombstone" / "board.json").exists()

    def test_active_watcher_blocks_purge(self, tmp_lkb_root: Path) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-watcher")
        store._active_watchers = 1
        with pytest.raises(LifecycleTransitionDenied, match="watcher"):
            purge_board(
                store,
                "purge-watcher",
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="purge-watcher",
                authorized=True,
            )
        assert board_lifecycle_state(store.load()) == "trashed"

    def test_actor_name_alone_does_not_grant_purge_permission(
        self, tmp_lkb_root: Path
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-auth")
        with pytest.raises(PermissionError):
            purge_board(
                store,
                "purge-auth",
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="purge-auth",
            )

    def test_unverified_archive_entry_blocks_before_tombstone(
        self, tmp_lkb_root: Path
    ) -> None:
        store = _create_store(
            tmp_lkb_root / "boards" / "purge-archive",
            board_id="purge-archive",
            home=tmp_lkb_root,
        )
        close_board(
            store, "purge-archive", actor="u", command_id="close", request_hash="hc"
        )
        archive_board(
            store,
            "purge-archive",
            actor="u",
            command_id="archive",
            request_hash="ha",
        )
        trash_board(
            store, "purge-archive", actor="u", command_id="trash", request_hash="ht"
        )
        archive_dir = Path(store.load().lifecycle["archive_info"]["archive_path"]).parent
        (archive_dir / "unverified.bin").write_bytes(b"?")
        with pytest.raises(LifecycleTransitionDenied, match="unverified archive"):
            purge_board(
                store,
                "purge-archive",
                actor="admin",
                command_id="purge",
                request_hash="hp",
                reason="cleanup",
                confirm="purge-archive",
                authorized=True,
            )
        assert board_lifecycle_state(store.load()) == "trashed"
        assert not list((tmp_lkb_root / "tombstones").glob("*.json"))

    def test_old_store_and_direct_create_cannot_resurrect(
        self, tmp_lkb_root: Path
    ) -> None:
        store = self._trashed_store(tmp_lkb_root, "purge-resurrection")
        purge_board(
            store,
            "purge-resurrection",
            actor="admin",
            command_id="purge",
            request_hash="hp",
            reason="cleanup",
            confirm="purge-resurrection",
            authorized=True,
        )
        with pytest.raises(BoardTombstonedError):
            store.execute_atomic(
                "purge-resurrection",
                "old-session",
                "old-hash",
                None,
                lambda env: (
                    env,
                    CommandResult(decision="committed", command_id="old-session"),
                ),
                actor="old-session",
            )
        with pytest.raises(BoardTombstonedError):
            store.read_snapshot()
        with pytest.raises(BoardTombstonedError):
            _create_store(
                tmp_lkb_root / "boards" / "purge-resurrection",
                board_id="purge-resurrection",
                home=tmp_lkb_root,
            )


class TestGcObservationRevalidation:
    def test_candidate_records_observation_and_changed_temp_is_retained(
        self, tmp_lkb_root: Path
    ) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "observed" / ".tmp"
        tmp_dir.mkdir(parents=True)
        item = tmp_dir / ".board.json.observed.tmp"
        item.write_text("old", encoding="utf-8")
        now = 8_000_000.0
        old = now - GC_TEMP_AGE_SECONDS - 1
        os.utime(item, (old, old))
        candidate = next(
            value
            for value in gc_scan(tmp_lkb_root, dry_run=True, now=now)
            if value.path == item
        )
        assert candidate.root == tmp_lkb_root
        assert candidate.observed_mtime_ns is not None
        assert candidate.observed_hash.startswith("sha256:")
        item.write_text("new owner", encoding="utf-8")
        gc_apply([candidate], now=now)
        assert item.is_file()

    def test_open_session_board_is_not_collected(self, tmp_lkb_root: Path) -> None:
        store = _create_session_store(tmp_lkb_root, "open-session")
        board_dir = Path(store._board_dir)
        board_json = board_dir / "board.json"
        now = 9_000_000.0
        old = now - GC_SESSION_ORPHAN_AGE_SECONDS - 1
        os.utime(board_json, (old, old))
        assert not any(
            value.kind == "session_orphan"
            for value in gc_scan(
                tmp_lkb_root,
                dry_run=False,
                now=now,
                open_board_ids={"open-session"},
            )
        )
        assert board_json.is_file()

    def test_checksum_damaged_board_is_reported_and_retained(
        self, tmp_lkb_root: Path
    ) -> None:
        board_id = "damaged-project"
        board_dir = (
            tmp_lkb_root / "boards" / safe_board_id(board_id)
        )
        store = _create_store(board_dir, board_id=board_id, home=tmp_lkb_root)
        board_json = Path(store._board_json)
        data = json.loads(board_json.read_text(encoding="utf-8"))
        data["lifecycle"]["scope"] = "session"
        board_json.write_text(json.dumps(data), encoding="utf-8")
        now = 11_000_000.0
        old = now - GC_SESSION_ORPHAN_AGE_SECONDS - 1
        os.utime(board_json, (old, old))

        candidates = gc_scan(tmp_lkb_root, dry_run=False, now=now)
        assert any(
            candidate.kind == "invalid_board" and candidate.path == board_json
            for candidate in candidates
        )
        assert board_json.is_file()

    def test_hash_valid_forged_session_scope_on_project_is_retained(
        self, tmp_lkb_root: Path
    ) -> None:
        board_id = "forged-project"
        board_dir = tmp_lkb_root / "boards" / safe_board_id(board_id)
        store = _create_store(board_dir, board_id=board_id, home=tmp_lkb_root)
        envelope = store.load()
        envelope.lifecycle["scope"] = "session"
        set_payload_hash(envelope, previous_hash=None)
        board_json = Path(store._board_json)
        board_json.write_text(json.dumps(envelope.to_dict()), encoding="utf-8")
        now = 12_000_000.0
        old = now - GC_SESSION_ORPHAN_AGE_SECONDS - 1
        os.utime(board_json, (old, old))

        candidates = gc_scan(tmp_lkb_root, dry_run=False, now=now)
        assert any(candidate.kind == "invalid_board" for candidate in candidates)
        assert board_json.is_file()

    def test_descendant_symlink_prevents_directory_action(self, tmp_lkb_root: Path) -> None:
        tmp_dir = tmp_lkb_root / "boards" / "descendant" / ".tmp"
        tmp_dir.mkdir(parents=True)
        suspicious = tmp_dir / "old-tree"
        suspicious.mkdir()
        outside = tmp_lkb_root / "outside"
        outside.mkdir()
        marker = outside / "marker"
        marker.write_text("keep", encoding="utf-8")
        try:
            (suspicious / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlink unavailable")
        now = 10_000_000.0
        old = now - GC_TEMP_AGE_SECONDS - 1
        os.utime(suspicious, (old, old))
        candidates = gc_scan(tmp_lkb_root, dry_run=False, now=now)
        assert any(value.path == suspicious for value in candidates)
        assert suspicious.is_dir()
        assert marker.is_file()
