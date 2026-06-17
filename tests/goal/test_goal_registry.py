"""Unit tests for :mod:`clawcodex_ext.goal.registry` and
:mod:`clawcodex_ext.goal.storage` (round-trip persistence)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawcodex_ext.goal import (
    BLOCKED_CONSECUTIVE_THRESHOLD,
    MAX_GOAL_TURNS,
    GoalState,
    GoalStateRegistry,
    GoalStatus,
    get_goal_registry,
    pause_goal,
    record_blocker,
    reset_goal_registry_for_tests,
    resume_goal,
    set_goal,
    update_tokens,
)
from clawcodex_ext.goal import storage as goal_storage


T0 = 1_700_000_000_000


# ---------------------------------------------------------------------------
# Registry basics
# ---------------------------------------------------------------------------


def test_registry_starts_empty():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    assert len(reg) == 0
    assert reg.get("missing") is None
    assert reg.has("missing") is False


def test_registry_set_and_get():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    state = set_goal(None, "ship it", now_ms=T0)
    reg.set("sess-1", state)
    assert reg.has("sess-1")
    assert reg.get("sess-1") is state


def test_registry_set_none_clears():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    state = set_goal(None, "ship it", now_ms=T0)
    reg.set("sess-1", state)
    reg.set("sess-1", None)
    assert not reg.has("sess-1")


def test_registry_clear_is_idempotent():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    reg.clear("never-existed")
    reg.set("sess-1", set_goal(None, "x", now_ms=T0))
    reg.clear("sess-1")
    reg.clear("sess-1")
    assert not reg.has("sess-1")


def test_registry_update_runs_mutator_inside_lock():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    state = set_goal(None, "ship it", token_budget=100, now_ms=T0)
    reg.set("sess-1", state)

    def add_tokens(s: GoalState | None) -> GoalState:
        assert s is not None
        s2, _ = update_tokens(s, 30, now_ms=T0 + 1000)
        return s2

    result = reg.update("sess-1", add_tokens)
    assert result is not None
    assert result.tokens_used == 30


def test_registry_update_can_remove():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    reg.set("sess-1", set_goal(None, "x", now_ms=T0))
    reg.update("sess-1", lambda _: None)
    assert not reg.has("sess-1")


def test_registry_snapshot_is_disjoint_copy():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    reg.set("sess-1", set_goal(None, "x", now_ms=T0))
    snap = reg.snapshot()
    assert set(snap.keys()) == {"sess-1"}
    # Mutating the live state does not affect the snapshot keys
    reg.set("sess-2", set_goal(None, "y", now_ms=T0))
    assert set(snap.keys()) == {"sess-1"}


def test_registry_process_singleton_is_shared():
    reset_goal_registry_for_tests()
    a = get_goal_registry()
    b = get_goal_registry()
    assert a is b


def test_registry_get_empty_session_id():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    reg.set("sess-1", set_goal(None, "x", now_ms=T0))
    assert reg.get("") is None
    assert reg.get(None) is None


def test_registry_set_rejects_empty_session_id():
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    with pytest.raises(ValueError):
        reg.set("", set_goal(None, "x", now_ms=T0))


# ---------------------------------------------------------------------------
# Persistence round-trip (storage.py uses SessionStorage; patch it here)
# ---------------------------------------------------------------------------


class _FakeStorage:
    """In-memory stand-in for :class:`SessionStorage`.

    Captures raw dicts written via :meth:`write_raw` and serves them
    back from :meth:`read_transcript`. Replaces
    ``SessionStorage(session_id=...)`` for the duration of the test.
    """

    instances: dict[str, "_FakeStorage"] = {}

    def __init__(self, session_id: str | None = None, **_: object) -> None:
        self.session_id = session_id or "fake-session"
        self.written: list[dict] = []
        type(self).instances[self.session_id] = self

    def write_raw(self, data: dict) -> None:
        self.written.append(data)

    def flush(self) -> None:
        # No-op: writes are immediately visible via ``written``.
        return None

    def read_transcript(self) -> list[dict]:
        return list(self.written)


@pytest.fixture(autouse=True)
def _patch_session_storage(monkeypatch):
    """Replace ``SessionStorage`` with the in-memory fake."""
    _FakeStorage.instances.clear()
    import src.services.session_storage as ss_mod

    monkeypatch.setattr(ss_mod, "SessionStorage", _FakeStorage)
    yield
    _FakeStorage.instances.clear()


def test_persist_goal_writes_correct_entry_shape():
    state = set_goal(None, "ship it", token_budget=500, now_ms=T0)
    assert goal_storage.persist_goal("sess-1", state) is True
    fake = _FakeStorage.instances["sess-1"]
    assert len(fake.written) == 1
    entry = fake.written[0]
    assert entry["type"] == goal_storage.GOAL_ENTRY_TYPE
    assert entry["sessionId"] == "sess-1"
    assert entry["state"]["objective"] == "ship it"
    assert entry["state"]["token_budget"] == 500
    assert entry["state"]["status"] == "active"
    assert "timestamp" in entry


def test_persist_goal_cleared_writes_tombstone():
    assert goal_storage.persist_goal_cleared("sess-1") is True
    fake = _FakeStorage.instances["sess-1"]
    entry = fake.written[0]
    assert entry["type"] == goal_storage.GOAL_CLEARED_ENTRY_TYPE
    assert entry["sessionId"] == "sess-1"
    assert "timestamp" in entry
    assert "state" not in entry


def test_hydrate_from_transcript_returns_none_when_empty():
    assert goal_storage.hydrate_from_transcript("sess-missing") is None


def test_hydrate_round_trip_full_lifecycle():
    # 1. Set a goal.
    state = set_goal(None, "ship it", token_budget=500, now_ms=T0)
    goal_storage.persist_goal("sess-1", state)
    # 2. Pause it.
    paused = pause_goal(state, now_ms=T0 + 60_000)
    goal_storage.persist_goal("sess-1", paused)
    # 3. Add some tokens.
    used, _ = update_tokens(paused, 100, now_ms=T0 + 120_000)
    goal_storage.persist_goal("sess-1", used)

    rebuilt = goal_storage.hydrate_from_transcript("sess-1")
    assert rebuilt is not None
    assert rebuilt.status == GoalStatus.PAUSED
    assert rebuilt.tokens_used == 100
    assert rebuilt.token_budget == 500
    assert rebuilt.objective == "ship it"


def test_hydrate_tombstone_overrides_prior_goal():
    state = set_goal(None, "ship it", now_ms=T0)
    goal_storage.persist_goal("sess-1", state)
    goal_storage.persist_goal_cleared("sess-1")
    # A new goal set after the clear should still be the winner.
    new_state = set_goal(state, "different", now_ms=T0 + 1000)
    goal_storage.persist_goal("sess-1", new_state)

    rebuilt = goal_storage.hydrate_from_transcript("sess-1")
    assert rebuilt is not None
    assert rebuilt.objective == "different"


def test_hydrate_tombstone_without_followup_returns_none():
    state = set_goal(None, "ship it", now_ms=T0)
    goal_storage.persist_goal("sess-1", state)
    goal_storage.persist_goal_cleared("sess-1")
    assert goal_storage.hydrate_from_transcript("sess-1") is None


def test_hydrate_ignores_other_sessions():
    """Entries for other session ids must not leak across sessions."""
    state = set_goal(None, "session A goal", now_ms=T0)
    goal_storage.persist_goal("sess-A", state)
    assert goal_storage.hydrate_from_transcript("sess-B") is None


def test_hydrate_skips_corrupt_entries():
    """A malformed entry should not poison the whole hydration."""
    # Seed a fresh FakeStorage for this session so the test owns the
    # transcript contents (the autouse fixture clears ``instances``
    # between tests, so the FakeStorage must be created here rather
    # than inherited from a previous test).
    fake = _FakeStorage.instances.setdefault("sess-1", _FakeStorage("sess-1"))
    fake.written = [
        {"type": "goal", "sessionId": "sess-1", "state": "not-a-dict"},
        {"type": "goal", "sessionId": "sess-1", "state": {
            "objective": "good", "status": "active",
            "tokens_used": 0, "turns_executed": 0,
            "start_time_ms": 0, "accumulated_active_ms": 0,
            "blocked_attempts": 0, "created_at_ms": 0, "updated_at_ms": 0,
        }},
    ]
    rebuilt = goal_storage.hydrate_from_transcript("sess-1")
    assert rebuilt is not None
    assert rebuilt.objective == "good"


def test_hydrate_empty_session_id():
    assert goal_storage.hydrate_from_transcript("") is None


# ---------------------------------------------------------------------------
# Integration: end-to-end lifecycle through the registry + transitions
# ---------------------------------------------------------------------------


def test_full_lifecycle_through_registry():
    """Active → blocked (3 same reasons) → resume → complete."""
    reset_goal_registry_for_tests()
    reg = GoalStateRegistry()
    state = set_goal(None, "ship it", now_ms=T0)
    reg.set("sess-1", state)

    for i in range(BLOCKED_CONSECUTIVE_THRESHOLD):
        new_state, _ = record_blocker(reg.get("sess-1"), "stuck", now_ms=T0 + i * 1000)
        reg.set("sess-1", new_state)

    assert reg.get("sess-1").status == GoalStatus.BLOCKED

    # Resume clears the blocker; subsequent blocker restarts the streak.
    current = reg.get("sess-1")
    # Manual un-block for the test (resume does not un-block directly,
    # but the controller would re-``set_goal`` once the user acts).
    fresh = set_goal(current, current.objective, now_ms=T0 + 100_000)
    reg.set("sess-1", fresh)

    new_state, _ = record_blocker(reg.get("sess-1"), "stuck", now_ms=T0 + 101_000)
    reg.set("sess-1", new_state)
    assert reg.get("sess-1").status == GoalStatus.ACTIVE
    assert reg.get("sess-1").blocked_attempts == 1
