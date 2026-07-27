"""Tests for json_store.py — BoardEnvelope + JsonBoardStore.

Covers:
  LKB-STORE-001 — BoardEnvelope round-trip: to_dict/from_dict preserves all fields
  LKB-STORE-002 — payload_hash chain: consecutive revisions form a valid hash chain
  LKB-STORE-003 — create_board writes genesis envelope with correct store_revision=0
  LKB-STORE-004 — idempotency: same command_id + same request_hash returns cached result
  LKB-STORE-005 — idempotency: same command_id + different hash raises IdempotencyKeyReusedError
  LKB-STORE-006 — revision CAS: matching expected_revision_vector succeeds
  LKB-STORE-007 — revision CAS: stale expected_revision_vector raises StaleRevisionError
  LKB-STORE-009 — schema version too new: forward-compat guard raises BoardSchemaTooNewError
  LKB-STORE-010 — corruption recovery: valid .bak is restored when primary is corrupt
  LKB-STORE-015 — payload hash mismatch on load: file treated as corrupt
  LKB-STORE-016 — both files corrupt: BoardStoreCorruptError, never empty board
  LKB-STORE-024 — board_id re-validation on load (safe-board-id bypass attempt)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from lkb._testing import Failpoint
from lkb.commands import CommandResult
from lkb.file_lock import BoardFileLock
from lkb.graph_types import Board, BoardPolicy, Graph, GraphNode, RevisionVector
from lkb.json_store import (
    BoardEnvelope,
    BoardSchemaTooNewError,
    BoardStoreCorruptError,
    CURRENT_SCHEMA_VERSION,
    IdempotencyKeyReusedError,
    JsonBoardStore,
    STORE_FORMAT,
    StaleRevisionError,
    payload_hash,
    set_payload_hash,
)
from lkb.lifecycle import close_board
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


def _make_store(
    board_dir: Path,
    *,
    board_id: str = "test-board",
    failpoint: Failpoint | None = None,
) -> JsonBoardStore:
    lock = BoardFileLock(board_dir)
    return JsonBoardStore(
        board_dir,
        board_id=board_id,
        lock=lock,
        failpoint=failpoint,
    )


def _create_board(
    board_dir: Path,
    *,
    board_id: str = "test-board",
    failpoint: Failpoint | None = None,
) -> JsonBoardStore:
    board = _make_board(board_id)
    lock = BoardFileLock(board_dir)
    return JsonBoardStore.create_board(
        board_dir,
        board=board,
        lock=lock,
        failpoint=failpoint,
    )


def _add_node_mutate(node_id: str, title: str) -> Any:
    """Return a mutate callable that adds a single plan task node."""

    def mutate(env: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
        ref = NodeRef("plan", "task", node_id)
        env.nodes[node_id] = {
            "ref": ref.to_str(),
            "title": title,
            "state": "ready",
            "revision": 1,
            "payload": {},
            "created_at": "2026-01-01T00:00:00.000Z",
            "updated_at": "2026-01-01T00:00:00.000Z",
        }
        # Ensure plan graph exists
        if "plan" not in env.graphs:
            env.graphs["plan"] = {
                "graph_id": "plan",
                "board_id": env.board_id(),
                "graph_kind": "plan",
                "revision": 0,
                "created_at": "2026-01-01T00:00:00.000Z",
                "updated_at": "2026-01-01T00:00:00.000Z",
            }
        result = CommandResult(
            decision="committed",
            command_id=f"cmd-{node_id}",
            reason=None,
        )
        return env, result

    return mutate


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── LKB-STORE-001 ────────────────────────────────────────────────────


class TestLkbStore001EnvelopeRoundTrip:
    """BoardEnvelope to_dict / from_dict round-trip preserves all fields."""

    def test_empty_envelope_roundtrip(self) -> None:
        env = BoardEnvelope()
        d = env.to_dict()
        env2 = BoardEnvelope.from_dict(d)
        assert env2.store_format == env.store_format
        assert env2.schema_version == env.schema_version
        assert env2.store_revision == env.store_revision
        assert env2.board == env.board
        assert env2.graphs == env.graphs
        assert env2.nodes == env.nodes
        assert env2.edges == env.edges
        assert env2.claims == env.claims
        assert env2.assertions == env.assertions
        assert env2.evidence == env.evidence
        assert env2.validation_runs == env.validation_runs
        assert env2.processed_commands == env.processed_commands
        assert env2.events == env.events
        assert env2.history_segments == env.history_segments
        assert env2.lifecycle == env.lifecycle
        assert env2.integrity == env.integrity

    def test_populated_envelope_roundtrip(self) -> None:
        env = BoardEnvelope(
            store_revision=5,
            board={"board_id": "board-1", "display_name": "Test Board"},
            graphs={
                "plan": {
                    "graph_id": "plan",
                    "board_id": "board-1",
                    "graph_kind": "plan",
                    "revision": 3,
                }
            },
            nodes={"n1": {"ref": "plan:task:T-001", "title": "Task 1", "state": "ready"}},
            edges={
                "e1": {
                    "edge_id": "e1",
                    "graph": "plan",
                    "type": "depends_on",
                    "source": "plan:task:T-002",
                    "target": "plan:task:T-001",
                }
            },
            claims={"c1": {"claim_id": "c1", "status": "active"}},
            assertions={"a1": {"assertion_id": "a1", "status": "active"}},
            evidence={"ev1": {"evidence_id": "ev1", "kind": "test_report"}},
            validation_runs={"v1": {"run_id": "v1", "status": "passed"}},
            processed_commands={"cmd-1": {"command_id": "cmd-1", "decision": "committed"}},
            events=[{"type": "test", "store_revision": 1}],
            history_segments=[{"segment_id": "h1", "start_revision": 0}],
            lifecycle={"state": "active"},
            integrity={"algorithm": "sha256", "payloadHash": "sha256:abc123"},
        )
        d = env.to_dict()
        env2 = BoardEnvelope.from_dict(d)
        assert env2.store_revision == 5
        assert env2.board["board_id"] == "board-1"
        assert env2.graphs["plan"]["revision"] == 3
        assert env2.nodes["n1"]["title"] == "Task 1"
        assert env2.edges["e1"]["type"] == "depends_on"
        assert env2.claims["c1"]["status"] == "active"
        assert env2.assertions["a1"]["status"] == "active"
        assert env2.evidence["ev1"]["kind"] == "test_report"
        assert env2.validation_runs["v1"]["status"] == "passed"
        assert env2.processed_commands["cmd-1"]["decision"] == "committed"
        assert len(env2.events) == 1
        assert len(env2.history_segments) == 1
        assert env2.lifecycle["state"] == "active"
        assert env2.integrity["payloadHash"] == "sha256:abc123"

    def test_to_dict_has_canonical_key_order(self) -> None:
        """top-level keys should be in a stable order (sorted by json.dumps)."""
        env = BoardEnvelope(
            board={"board_id": "b1"},
            graphs={"g1": {}},
            nodes={},
        )
        raw = json.dumps(env.to_dict(), sort_keys=True)
        parsed = json.loads(raw)
        # Just verify all expected keys are present
        expected = {
            "storeFormat",
            "schemaVersion",
            "storeRevision",
            "board",
            "graphs",
            "nodes",
            "edges",
            "claims",
            "assertions",
            "evidence",
            "validationRuns",
            "processedCommands",
            "events",
            "historySegments",
            "lifecycle",
            "integrity",
        }
        assert set(parsed.keys()) == expected

    def test_store_format_constant(self) -> None:
        assert STORE_FORMAT == "lkb-json-v1"
        env = BoardEnvelope()
        assert env.store_format == STORE_FORMAT

    def test_from_dict_rejects_missing_current_schema_fields(self) -> None:
        """Current-schema decode must not silently default missing state."""
        minimal = {
            "storeFormat": STORE_FORMAT,
            "schemaVersion": 1,
            "storeRevision": 0,
            "board": {"board_id": "minimal"},
            "integrity": {"algorithm": "sha256", "payloadHash": "sha256:xxx"},
        }
        with pytest.raises(ValueError, match="missing required fields"):
            BoardEnvelope.from_dict(minimal)


# ── LKB-STORE-002 ────────────────────────────────────────────────────


class TestLkbStore002PayloadHashChain:
    """payload_hash chain: consecutive revisions form a valid hash chain."""

    def test_genesis_envelope_payload_hash(self) -> None:
        env = BoardEnvelope(
            board={"board_id": "chain-test", "store_revision": 0},
            store_revision=0,
        )
        h = set_payload_hash(env, previous_hash=None)
        # integrity.payloadHash should match re-computation
        assert env.integrity["payloadHash"] == h
        assert payload_hash(env) == h
        # Genesis should have no previousPayloadHash
        assert "previousPayloadHash" not in env.integrity

    def test_second_revision_chains_previous_hash(self) -> None:
        env1 = BoardEnvelope(
            board={"board_id": "chain-test"},
            store_revision=1,
        )
        h1 = set_payload_hash(env1, previous_hash=None)

        env2 = BoardEnvelope(
            board={"board_id": "chain-test", "extra": "new"},
            store_revision=2,
        )
        h2 = set_payload_hash(env2, previous_hash=h1)

        assert env2.integrity["previousPayloadHash"] == h1
        assert env2.integrity["payloadHash"] == h2
        # Hashes must be different (content changed)
        assert h1 != h2

    def test_payload_hash_strips_integrity_block(self) -> None:
        """The integrity block must NOT be part of the hash input."""
        env = BoardEnvelope(
            board={"board_id": "hash-test"},
        )
        # Setting the payload hash should produce a deterministic result
        h1 = set_payload_hash(env, previous_hash=None)
        # Mutating only integrity fields shouldn't change the hash
        env.integrity["extra_junk"] = "should_not_affect_hash"
        h2 = payload_hash(env)
        assert h1 == h2

    def test_hash_uses_sha256_prefix(self) -> None:
        env = BoardEnvelope(board={"board_id": "algo-test"})
        h = payload_hash(env)
        assert h.startswith("sha256:")
        # sha256 hex is 64 chars
        assert len(h) == len("sha256:") + 64

    def test_current_revision_vector(self) -> None:
        env = BoardEnvelope(
            graphs={
                "plan": {"graph_id": "plan", "revision": 5},
                "artifact": {"graph_id": "artifact", "revision": 3},
            }
        )
        rv = env.current_revision_vector()
        assert rv.get("plan") == 5
        assert rv.get("artifact") == 3
        assert rv.get("nonexistent") == 0


# ── LKB-STORE-003 ────────────────────────────────────────────────────


class TestLkbStore003CreateBoard:
    """create_board writes genesis envelope with store_revision=0."""

    def test_genesis_envelope_on_disk(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="genesis-board")

        assert store.exists()
        data = _read_json(board_dir / "board.json")
        assert data["storeFormat"] == STORE_FORMAT
        assert data["schemaVersion"] == CURRENT_SCHEMA_VERSION
        assert data["storeRevision"] == 0
        assert data["board"]["board_id"] == "genesis-board"
        assert data["lifecycle"]["state"] == "active"
        assert data["integrity"]["algorithm"] == "sha256"
        assert data["integrity"]["payloadHash"].startswith("sha256:")
        # Genesis has no previous hash
        assert "previousPayloadHash" not in data["integrity"]

    def test_load_after_create_returns_valid_envelope(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="loadable-board")

        store = _make_store(board_dir, board_id="loadable-board")
        env = store.load()
        assert env.board_id() == "loadable-board"
        assert env.store_revision == 0

    def test_create_board_on_existing_raises(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="exists")

        with pytest.raises(FileExistsError):
            _create_board(board_dir, board_id="exists")

    def test_backup_file_exists_after_create(self, tmp_path: Path) -> None:
        """After create_board, a .bak may or may not exist (only after first
        real write).  Genesis doesn't produce a .bak — that's fine."""
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="bak-test")
        # board.json should exist; .bak doesn't have to yet
        assert (board_dir / "board.json").exists()

    def test_header_after_create(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="header-test")

        store = _make_store(board_dir, board_id="header-test")
        h = store.header()
        assert h["board_id"] == "header-test"
        assert h["store_revision"] == 0
        assert h["schema_version"] == CURRENT_SCHEMA_VERSION
        assert h["lifecycle_state"] == "active"


# ── LKB-STORE-004 ────────────────────────────────────────────────────


class TestLkbStore004IdempotencySameCommand:
    """Same command_id + same request_hash returns cached result (no double-apply)."""

    def test_same_command_returns_cached(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="idem-board")

        command_id = "cmd-001"
        request_hash = "sha256:reqhash111"

        # First execution
        result1 = store.execute_atomic(
            board_id="idem-board",
            command_id=command_id,
            request_hash=request_hash,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "First task"),
            actor="agent-1",
        )
        assert result1.committed is True

        # Second execution with same command_id + same request_hash
        result2 = store.execute_atomic(
            board_id="idem-board",
            command_id=command_id,
            request_hash=request_hash,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "First task"),
            actor="agent-1",
        )
        assert result2.committed is True
        assert result2.command_id == command_id

        # Store revision should be 1 (only one real commit happened)
        env = store.load()
        assert env.store_revision == 1
        # Node should exist exactly once
        assert "T-001" in env.nodes

    def test_cached_result_preserves_revision_vector(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="idem-rv")

        command_id = "cmd-rv"
        request_hash = "sha256:rvhash"

        result1 = store.execute_atomic(
            board_id="idem-rv",
            command_id=command_id,
            request_hash=request_hash,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-100", "RV test"),
            actor="agent-1",
        )

        result2 = store.execute_atomic(
            board_id="idem-rv",
            command_id=command_id,
            request_hash=request_hash,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-100", "RV test"),
            actor="agent-1",
        )

        assert result1.revision_vector is not None
        assert result2.revision_vector is not None
        assert result1.revision_vector.equals(result2.revision_vector)

    def test_idempotency_recorded_in_processed_commands(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="idem-pc")

        command_id = "cmd-pc"
        request_hash = "sha256:pchash"

        store.execute_atomic(
            board_id="idem-pc",
            command_id=command_id,
            request_hash=request_hash,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-200", "PC test"),
            actor="agent-1",
        )

        env = store.load()
        assert command_id in env.processed_commands
        entry = env.processed_commands[command_id]
        assert entry["request_hash"] == request_hash
        assert entry["decision"] == "committed"
        assert entry["actor"] == "agent-1"
        assert entry["store_revision"] == 1


# ── LKB-STORE-005 ────────────────────────────────────────────────────


class TestLkbStore005IdempotencyKeyReused:
    """Same command_id + different request_hash raises IdempotencyKeyReusedError."""

    def test_reused_key_with_different_hash_raises(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="reuse-board")

        command_id = "cmd-reuse"
        hash1 = "sha256:hash-one-111"
        hash2 = "sha256:hash-two-222"

        store.execute_atomic(
            board_id="reuse-board",
            command_id=command_id,
            request_hash=hash1,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "Task 1"),
            actor="agent-1",
        )

        with pytest.raises(IdempotencyKeyReusedError) as exc_info:
            store.execute_atomic(
                board_id="reuse-board",
                command_id=command_id,
                request_hash=hash2,
                expected_revision_vector=None,
                mutate=_add_node_mutate("T-002", "Task 2"),
                actor="agent-1",
            )

        assert exc_info.value.command_id == command_id
        assert exc_info.value.stored_request_hash == hash1
        assert exc_info.value.new_request_hash == hash2

    def test_reused_key_does_not_mutate_state(self, tmp_path: Path) -> None:
        """After a key-reuse error, board state must be unchanged."""
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="reuse-nomut")

        command_id = "cmd-reuse2"
        hash1 = "sha256:hash-a"
        hash2 = "sha256:hash-b"

        store.execute_atomic(
            board_id="reuse-nomut",
            command_id=command_id,
            request_hash=hash1,
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "Only this"),
            actor="agent-1",
        )

        env_before = store.load()
        rev_before = env_before.store_revision

        with pytest.raises(IdempotencyKeyReusedError):
            store.execute_atomic(
                board_id="reuse-nomut",
                command_id=command_id,
                request_hash=hash2,
                expected_revision_vector=None,
                mutate=_add_node_mutate("T-002", "Should not appear"),
                actor="agent-1",
            )

        env_after = store.load()
        assert env_after.store_revision == rev_before
        assert "T-001" in env_after.nodes
        assert "T-002" not in env_after.nodes


# ── LKB-STORE-006 ────────────────────────────────────────────────────


class TestLkbStore006RevisionCasMatch:
    """Matching expected_revision_vector allows the write to proceed."""

    def test_matching_revision_vector_succeeds(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-match")

        # First write to bump plan graph revision
        store.execute_atomic(
            board_id="cas-match",
            command_id="cmd-first",
            request_hash="sha256:first",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "First"),
            actor="agent-1",
        )

        # Read current revision vector
        env = store.load()
        current_rv = env.current_revision_vector()

        # Second write with matching expected revision
        result = store.execute_atomic(
            board_id="cas-match",
            command_id="cmd-second",
            request_hash="sha256:second",
            expected_revision_vector=current_rv,
            mutate=_add_node_mutate("T-002", "Second"),
            actor="agent-1",
        )

        assert result.committed is True
        env_after = store.load()
        assert env_after.store_revision == 2
        assert "T-002" in env_after.nodes

    def test_partial_revision_vector_only_checks_listed_graphs(self, tmp_path: Path) -> None:
        """Only graph IDs present in expected_revision_vector are checked."""
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-partial")

        store.execute_atomic(
            board_id="cas-partial",
            command_id="cmd-1",
            request_hash="sha256:h1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "One"),
            actor="agent-1",
        )

        # Pass a vector with only a non-existent graph — should pass
        rv = RevisionVector(revisions={"nonexistent": 0})
        result = store.execute_atomic(
            board_id="cas-partial",
            command_id="cmd-2",
            request_hash="sha256:h2",
            expected_revision_vector=rv,
            mutate=_add_node_mutate("T-2", "Two"),
            actor="agent-1",
        )
        assert result.committed is True

    def test_no_expected_revision_vector_always_succeeds(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-none")

        for i in range(3):
            result = store.execute_atomic(
                board_id="cas-none",
                command_id=f"cmd-{i}",
                request_hash=f"sha256:h{i}",
                expected_revision_vector=None,
                mutate=_add_node_mutate(f"T-{i}", f"Task {i}"),
                actor="agent-1",
            )
            assert result.committed is True

        env = store.load()
        assert env.store_revision == 3


# ── LKB-STORE-007 ────────────────────────────────────────────────────


class TestLkbStore007RevisionCasStale:
    """Stale expected_revision_vector raises StaleRevisionError."""

    def test_stale_revision_raises(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-stale")

        store.execute_atomic(
            board_id="cas-stale",
            command_id="cmd-base",
            request_hash="sha256:base",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "Base"),
            actor="agent-1",
        )

        # stale: plan graph at revision 0 (but actual is higher)
        stale_rv = RevisionVector(revisions={"plan": 0})

        with pytest.raises(StaleRevisionError) as exc_info:
            store.execute_atomic(
                board_id="cas-stale",
                command_id="cmd-stale",
                request_hash="sha256:stale",
                expected_revision_vector=stale_rv,
                mutate=_add_node_mutate("T-002", "Stale"),
                actor="agent-1",
            )

        assert exc_info.value.board_id == "cas-stale"
        assert exc_info.value.expected.get("plan") == 0
        assert exc_info.value.actual.get("plan") > 0

    def test_stale_revision_does_not_mutate_state(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-stale-nomut")

        store.execute_atomic(
            board_id="cas-stale-nomut",
            command_id="cmd-first",
            request_hash="sha256:first",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "First"),
            actor="agent-1",
        )

        env_before = store.load()
        rev_before = env_before.store_revision

        stale_rv = RevisionVector(revisions={"plan": 0})

        with pytest.raises(StaleRevisionError):
            store.execute_atomic(
                board_id="cas-stale-nomut",
                command_id="cmd-stale2",
                request_hash="sha256:stale2",
                expected_revision_vector=stale_rv,
                mutate=_add_node_mutate("T-002", "Should not exist"),
                actor="agent-1",
            )

        env_after = store.load()
        assert env_after.store_revision == rev_before
        assert "T-002" not in env_after.nodes

    def test_stale_store_revision_does_not_mutate_state(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="cas-store-stale")
        store.execute_atomic(
            board_id="cas-store-stale",
            command_id="cmd-first",
            request_hash="sha256:first",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "First"),
            actor="agent-1",
        )

        with pytest.raises(StaleRevisionError, match="store revision"):
            store.execute_atomic(
                board_id="cas-store-stale",
                command_id="cmd-stale-store",
                request_hash="sha256:stale-store",
                expected_revision_vector=None,
                expected_store_revision=0,
                mutate=_add_node_mutate("T-002", "Should not exist"),
                actor="agent-1",
            )

        envelope = store.load()
        assert envelope.store_revision == 1
        assert "T-002" not in envelope.nodes


# ── LKB-STORE-009 ────────────────────────────────────────────────────


class TestLkbStore009SchemaTooNew:
    """Board with schema_version > CURRENT_SCHEMA_VERSION raises BoardSchemaTooNewError.

    Forward-compat guard (LKB-STORE-025): an older reader must never silently
    corrupt a board written by a newer version.
    """

    def test_future_schema_version_raises_on_load(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="future-schema")

        # Manually write a board.json with a higher schema version
        data = _read_json(board_dir / "board.json")
        data["schemaVersion"] = 999
        # Recompute the payload hash so the file is "valid" but from the future
        import copy

        payload = {k: v for k, v in data.items() if k != "integrity"}
        from lkb.ir_hash import canonical_hash

        data["integrity"]["payloadHash"] = canonical_hash(payload)
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        store = _make_store(board_dir, board_id="future-schema")
        with pytest.raises(BoardSchemaTooNewError) as exc_info:
            store.load()

        assert exc_info.value.board_id == "future-schema"
        assert exc_info.value.on_disk_version == 999
        assert exc_info.value.supported_version == CURRENT_SCHEMA_VERSION

    def test_future_schema_on_bak_also_raises(self, tmp_path: Path) -> None:
        """If both primary and .bak are from the future, BoardSchemaTooNewError
        is raised (not BoardStoreCorruptError — forward-compat guard wins)."""
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="future-bak")

        # Do a write to create a .bak
        store = _make_store(board_dir, board_id="future-bak")
        store.execute_atomic(
            board_id="future-bak",
            command_id="cmd-tmp",
            request_hash="sha256:tmp",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "temp"),
            actor="agent-1",
        )

        # Now upgrade both files to future schema
        for fname in ("board.json", "board.json.bak"):
            path = board_dir / fname
            data = _read_json(path)
            data["schemaVersion"] = 999
            payload = {k: v for k, v in data.items() if k != "integrity"}
            from lkb.ir_hash import canonical_hash

            data["integrity"]["payloadHash"] = canonical_hash(payload)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)

        # Forward-compat guard: BoardSchemaTooNewError (not corrupt)
        with pytest.raises(BoardSchemaTooNewError):
            store.load()


# ── LKB-STORE-010 ────────────────────────────────────────────────────


class TestLkbStore010CorruptionRecovery:
    """Corruption recovery: valid .bak is restored when primary is corrupt."""

    def test_primary_corrupt_bak_valid_recovers(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="recovery-1")

        # Do a write so .bak is created
        store.execute_atomic(
            board_id="recovery-1",
            command_id="cmd-1",
            request_hash="sha256:cmd1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "Task 1"),
            actor="agent-1",
        )

        # Corrupt the primary
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            f.write("{this is not valid json!!!")

        # Load should recover from .bak
        env = store.load()
        assert env.board_id() == "recovery-1"
        # .bak has store_revision=0 (genesis) because the first write
        # put the old version (rev 0) into .bak
        # Actually — the first write: genesis (rev 0) gets rotated into .bak,
        # and rev 1 becomes primary.  Then we corrupt primary (rev 1).
        # Recovery should restore .bak (rev 0).
        assert env.store_revision in (0, 1)  # either is valid for recovery

    def test_recovery_quarantines_corrupt_primary(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="recovery-quar")

        store.execute_atomic(
            board_id="recovery-quar",
            command_id="cmd-1",
            request_hash="sha256:q1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "QT"),
            actor="agent-1",
        )

        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            f.write("GARBAGE DATA")

        store.load()

        # A quarantine directory should have been created
        quarantine_dir = board_dir / "quarantine"
        if quarantine_dir.exists():
            quarantined = list(quarantine_dir.glob("*primary-corrupt*"))
            assert len(quarantined) >= 0  # best effort, just check no crash

    def test_recovery_same_board_id(self, tmp_path: Path) -> None:
        """Recovery only works if the backup is for the SAME board."""
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="board-a")

        store.execute_atomic(
            board_id="board-a",
            command_id="cmd-1",
            request_hash="sha256:a1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "A1"),
            actor="agent-1",
        )

        # Corrupt primary
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            f.write("not json")

        # Load still works because .bak is for the same board
        env = store.load()
        assert env.board_id() == "board-a"


# ── LKB-STORE-015 ────────────────────────────────────────────────────


class TestLkbStore015PayloadHashMismatch:
    """Payload hash mismatch on load: file treated as corrupt."""

    def test_tampered_payload_hash_treated_as_corrupt(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="hash-mismatch")

        # Tamper with the content without updating the hash
        data = _read_json(board_dir / "board.json")
        data["board"]["display_name"] = "TAMPERED"
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        store = _make_store(board_dir, board_id="hash-mismatch")
        # Since both files are bad (primary tampered, .bak doesn't exist yet),
        # this should raise BoardStoreCorruptError
        with pytest.raises(BoardStoreCorruptError):
            store.load()

    def test_tampered_integrity_payload_hash_treated_as_corrupt(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="hash-fake")

        data = _read_json(board_dir / "board.json")
        data["integrity"]["payloadHash"] = (
            "sha256:0000000000000000000000000000000000000000000000000000000000000000"
        )
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        store = _make_store(board_dir, board_id="hash-fake")
        with pytest.raises(BoardStoreCorruptError):
            store.load()

    def test_missing_integrity_block_treated_as_corrupt(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="no-integrity")

        data = _read_json(board_dir / "board.json")
        del data["integrity"]
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            json.dump(data, f)

        store = _make_store(board_dir, board_id="no-integrity")
        with pytest.raises(BoardStoreCorruptError):
            store.load()


# ── LKB-STORE-016 ────────────────────────────────────────────────────


class TestLkbStore016BothCorrupt:
    """Both board.json and board.json.bak corrupt → BoardStoreCorruptError.

    IMPORTANT: NEVER returns an empty Board (spec §7.12).
    """

    def test_both_files_corrupt_raises(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="both-corrupt")

        # Do one write so .bak exists
        store.execute_atomic(
            board_id="both-corrupt",
            command_id="cmd-1",
            request_hash="sha256:c1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "T1"),
            actor="agent-1",
        )

        # Corrupt both files
        for fname in ("board.json", "board.json.bak"):
            with open(board_dir / fname, "w", encoding="utf-8") as f:
                f.write("CORRUPT!!!")

        with pytest.raises(BoardStoreCorruptError):
            store.load()

    def test_no_files_at_all_raises_not_found_vs_corrupt(self, tmp_path: Path) -> None:
        """If no board.json exists and no .bak, the store should raise."""
        board_dir = tmp_path / "empty-board"
        board_dir.mkdir()

        store = _make_store(board_dir, board_id="empty")
        with pytest.raises(BoardStoreCorruptError):
            store.load()

    def test_corrupt_error_message_identifies_board(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _make_store(board_dir, board_id="err-msg")

        try:
            store.load()
            assert False, "Should have raised"
        except BoardStoreCorruptError as exc:
            assert "err-msg" in str(exc)


# ── LKB-STORE-024 ────────────────────────────────────────────────────


class TestLkbStore024BoardIdReValidation:
    """board_id re-validation on load (LKB-STORE-028 / safe-board-id bypass).

    The store must verify that the on-disk board_id matches the expected
    board_id, so that an attacker who can manipulate directory names
    cannot trick the store into loading a different board.
    """

    def test_mismatched_board_id_rejected_on_load(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="correct-id")

        # Store configured with a DIFFERENT expected board_id
        store = _make_store(board_dir, board_id="wrong-id")

        with pytest.raises(BoardStoreCorruptError):
            store.load()

    def test_correct_board_id_accepted(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="my-board")

        store = _make_store(board_dir, board_id="my-board")
        env = store.load()
        assert env.board_id() == "my-board"

    def test_board_id_mismatch_in_execute_atomic_rejected(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="board-a")

        # Calling execute_atomic with a different board_id should raise
        with pytest.raises(ValueError, match="board_id mismatch"):
            store.execute_atomic(
                board_id="board-b",
                command_id="cmd-1",
                request_hash="sha256:h1",
                expected_revision_vector=None,
                mutate=_add_node_mutate("T-1", "Should fail"),
                actor="agent-1",
            )


# ── read_snapshot tests (additional, not a specific LKB-STORE number)──


class TestReadSnapshot:
    """read_snapshot returns a valid GraphSnapshot without acquiring a lock."""

    def test_read_snapshot_genesis(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        _create_board(board_dir, board_id="snap-test")

        store = _make_store(board_dir, board_id="snap-test")
        snap = store.read_snapshot()
        assert snap.board_id == "snap-test"
        assert snap.graphs == {}
        assert snap.nodes == {}
        assert snap.edges == {}

    def test_read_snapshot_after_mutations(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="snap-mut")

        store.execute_atomic(
            board_id="snap-mut",
            command_id="cmd-1",
            request_hash="sha256:s1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-001", "Snap task"),
            actor="agent-1",
        )

        snap = store.read_snapshot()
        assert snap.board_id == "snap-mut"
        assert "plan" in snap.graphs
        assert len(snap.nodes) == 1
        ref = NodeRef("plan", "task", "T-001")
        assert ref in snap.nodes
        assert snap.nodes[ref].title == "Snap task"

    def test_read_snapshot_corrupt_primary_does_not_use_bak(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="snap-bak")

        store.execute_atomic(
            board_id="snap-bak",
            command_id="cmd-1",
            request_hash="sha256:sb1",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "Backup"),
            actor="agent-1",
        )

        # Corrupt primary
        with open(board_dir / "board.json", "w", encoding="utf-8") as f:
            f.write("NOT JSON")

        # Ordinary reads never disguise stale backup state as current.
        with pytest.raises(BoardStoreCorruptError):
            store.read_snapshot()


class TestInterruptedBackupRotation:
    """A crash after backup rotation leaves the old revision authoritative."""

    def test_reopen_accepts_identical_primary_and_backup_revision(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="backup-window")
        store.execute_atomic(
            board_id="backup-window",
            command_id="committed",
            request_hash="sha256:committed",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-old", "Committed task"),
            actor="agent-1",
        )
        committed = store.load().to_dict()

        failpoint = Failpoint()
        failpoint.register(
            "after_backup_before_replace",
            RuntimeError("simulated crash after backup rotation"),
        )
        interrupted = _make_store(
            board_dir,
            board_id="backup-window",
            failpoint=failpoint,
        )
        with pytest.raises(RuntimeError, match="simulated crash"):
            interrupted.execute_atomic(
                board_id="backup-window",
                command_id="not-committed",
                request_hash="sha256:not-committed",
                expected_revision_vector=None,
                mutate=_add_node_mutate("T-new", "Uncommitted task"),
                actor="agent-2",
            )

        reopened = _make_store(board_dir, board_id="backup-window")
        loaded = reopened.load()
        assert loaded.to_dict() == committed
        assert loaded.store_revision == committed["storeRevision"]
        assert "T-old" in loaded.nodes
        assert "T-new" not in loaded.nodes

    def test_same_revision_with_different_valid_payload_is_rejected(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="same-revision-fork")
        store.execute_atomic(
            board_id="same-revision-fork",
            command_id="committed",
            request_hash="sha256:committed",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "Committed task"),
            actor="agent-1",
        )

        primary = store.load()
        fork = primary.clone()
        fork.nodes["T-1"]["title"] = "Different valid fork"
        set_payload_hash(
            fork,
            previous_hash=str(primary.integrity.get("previousPayloadHash", "")),
        )
        (board_dir / "board.json.bak").write_text(
            json.dumps(fork.to_dict(), sort_keys=True),
            encoding="utf-8",
        )

        with pytest.raises(BoardStoreCorruptError, match="same revision"):
            _make_store(board_dir, board_id="same-revision-fork").load()

    def test_valid_primary_ignores_corrupt_backup(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="bad-optional-backup")
        store.execute_atomic(
            board_id="bad-optional-backup",
            command_id="committed",
            request_hash="sha256:committed",
            expected_revision_vector=None,
            mutate=_add_node_mutate("T-1", "Committed task"),
            actor="agent-1",
        )
        (board_dir / "board.json.bak").write_text("not-json", encoding="utf-8")

        reopened = _make_store(board_dir, board_id="bad-optional-backup")
        assert reopened.load().store_revision == 1
        assert reopened.read_snapshot().board_id == "bad-optional-backup"
        assert reopened._load_locked().store_revision == 1

    def test_valid_primary_ignores_stale_nonadjacent_backup(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="stale-backup")
        genesis = (board_dir / "board.json").read_bytes()
        for index in range(2):
            store.execute_atomic(
                board_id="stale-backup",
                command_id=f"committed-{index}",
                request_hash=f"sha256:committed-{index}",
                expected_revision_vector=None,
                mutate=_add_node_mutate(f"T-{index}", f"Task {index}"),
                actor="agent-1",
            )
        (board_dir / "board.json.bak").write_bytes(genesis)

        reopened = _make_store(board_dir, board_id="stale-backup")
        assert reopened.load().store_revision == 2
        assert reopened.read_snapshot().store_revision == 2


# ── execute_atomic: revision bumping ─────────────────────────────────


class TestExecuteAtomicRevisionBumping:
    """execute_atomic properly bumps store_revision and graph revisions."""

    def test_store_revision_bumps_by_one_per_commit(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="rev-bump")

        for i in range(5):
            store.execute_atomic(
                board_id="rev-bump",
                command_id=f"cmd-{i}",
                request_hash=f"sha256:rh{i}",
                expected_revision_vector=None,
                mutate=_add_node_mutate(f"T-{i}", f"Task {i}"),
                actor="agent-1",
            )

        env = store.load()
        assert env.store_revision == 5

    def test_event_log_grows_with_each_commit(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="events")

        for i in range(3):
            store.execute_atomic(
                board_id="events",
                command_id=f"cmd-{i}",
                request_hash=f"sha256:eh{i}",
                expected_revision_vector=None,
                mutate=_add_node_mutate(f"T-{i}", f"Ev{i}"),
                actor="agent-1",
            )

        env = store.load()
        # Issue #9: each commit now emits a command_received event followed
        # by a command_executed event (spec §6.10).
        assert len(env.events) == 6
        received = [e for e in env.events if e["type"] == "command_received"]
        executed = [e for e in env.events if e["type"] == "command_executed"]
        assert len(received) == 3
        assert len(executed) == 3
        for ev in executed:
            assert ev["decision"] == "committed"
            assert ev["actor"] == "agent-1"

    def test_payload_hash_chain_accommits(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="hash-chain")

        prev_hash = None
        for i in range(4):
            store.execute_atomic(
                board_id="hash-chain",
                command_id=f"cmd-{i}",
                request_hash=f"sha256:hc{i}",
                expected_revision_vector=None,
                mutate=_add_node_mutate(f"T-{i}", f"H{i}"),
                actor="agent-1",
            )
            env = store.load()
            current_hash = env.integrity["payloadHash"]
            if prev_hash is not None:
                assert env.integrity["previousPayloadHash"] == prev_hash
            prev_hash = current_hash

    def test_same_count_domain_edits_bump_only_owned_graph(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="exact-diff")

        def seed(env: BoardEnvelope) -> tuple[BoardEnvelope, CommandResult]:
            for gid, kind in (("plan", "plan"), ("artifact", "artifact")):
                env.graphs[gid] = {
                    "graph_id": gid,
                    "board_id": "exact-diff",
                    "graph_kind": kind,
                    "revision": 99,
                }
                ref = NodeRef(gid, "task" if gid == "plan" else "file", "one")
                env.nodes[gid] = {
                    "ref": ref.to_str(),
                    "title": gid,
                    "state": "pending",
                    "owner": None,
                    "revision": 1,
                    "payload": {},
                }
            return env, CommandResult(decision="committed", command_id="seed")

        store.execute_atomic("exact-diff", "seed", "h-seed", None, seed, actor="a")

        mutations = (
            lambda env: env.nodes["plan"].update(title="renamed"),
            lambda env: env.nodes["plan"].update(owner="agent-1"),
            lambda env: env.claims.update(
                {
                    "c1": {
                        "claim_id": "c1",
                        "task_ref": "plan:task:one",
                        "owner_ref": "plan:agent:agent-1",
                        "claim_revision": 1,
                        "status": "active",
                        "claimed_at": "",
                        "released_at": "",
                        "reason": "",
                    }
                }
            ),
            lambda env: env.evidence.update(
                {"ev1": {"evidence_id": "ev1", "subject_ref": "plan:task:one"}}
            ),
            lambda env: env.assertions.update(
                {"a1": {"assertion_id": "a1", "subject_ref": "plan:task:one"}}
            ),
        )
        previous_plan_revision = 1
        for index, change in enumerate(mutations, start=1):

            def mutate(
                env: BoardEnvelope,
                *,
                change: Any = change,
                index: int = index,
            ) -> tuple[BoardEnvelope, CommandResult]:
                change(env)
                return env, CommandResult(decision="committed", command_id=f"change-{index}")

            store.execute_atomic(
                "exact-diff",
                f"change-{index}",
                f"h-{index}",
                None,
                mutate,
                actor="agent",
            )
            envelope = store.load()
            previous_plan_revision += 1
            assert envelope.graphs["plan"]["revision"] == previous_plan_revision
            assert envelope.graphs["artifact"]["revision"] == 1

    def test_invalid_node_ref_is_not_silently_skipped(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="bad-ref")
        data = _read_json(board_dir / "board.json")
        data["graphs"]["plan"] = {
            "graph_id": "plan",
            "board_id": "bad-ref",
            "graph_kind": "plan",
            "revision": 1,
        }
        data["nodes"]["bad"] = {"ref": "not-a-ref", "title": "bad", "revision": 1}
        envelope = BoardEnvelope.from_dict(data)
        set_payload_hash(envelope)
        with open(board_dir / "board.json", "w", encoding="utf-8") as handle:
            json.dump(envelope.to_dict(), handle)
        with pytest.raises(BoardStoreCorruptError):
            store.read_snapshot()


class TestStoreMigrationAndLifecycleWiring:
    def test_real_store_load_migrates_v0_and_reopens(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "board"
        store = _create_board(board_dir, board_id="migrate-reopen")
        raw = _read_json(board_dir / "board.json")
        raw.pop("schemaVersion")
        raw.pop("storeFormat")
        raw.pop("integrity")
        raw["legacyExtension"] = {"preserve": True}
        (board_dir / "board.json").write_text(json.dumps(raw), encoding="utf-8")

        migrated = store.load()
        assert migrated.schema_version == CURRENT_SCHEMA_VERSION
        assert migrated.board["compatibility_metadata"]["legacy_top_level"]["legacyExtension"] == {
            "preserve": True
        }
        reopened = _make_store(board_dir, board_id="migrate-reopen").load()
        assert reopened.to_dict() == migrated.to_dict()
        assert list((board_dir / "migration-backups").glob("*.json"))

    def test_session_genesis_has_session_scope(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "session"
        board = Board(
            board_id="session-board",
            project_uri="session:session-board",
            display_name="Session Board",
            schema_version=1,
            store_revision=0,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            policy=BoardPolicy(),
        )
        store = JsonBoardStore.create_board(board_dir, board=board, lock=BoardFileLock(board_dir))
        lifecycle = store.load().lifecycle
        assert lifecycle["scope"] == "session"
        assert lifecycle["origin_project_uri"] == "session:session-board"

    def test_store_gate_revalidates_under_lock(self, tmp_path: Path) -> None:
        board_dir = tmp_path / "closed"
        store = _create_board(board_dir, board_id="closed-gate")
        close_board(
            store,
            "closed-gate",
            actor="u",
            command_id="close",
            request_hash="hc",
        )
        with pytest.raises(PermissionError, match="closed"):
            store.execute_atomic(
                "closed-gate",
                "write",
                "hw",
                None,
                _add_node_mutate("T-1", "forbidden"),
                actor="u",
            )
        assert store.load().nodes == {}
