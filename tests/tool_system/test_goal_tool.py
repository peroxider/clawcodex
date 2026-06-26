"""Unit tests for :mod:`clawcodex_ext.goal.tool` (the ``Goal`` tool)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

from clawcodex_ext.goal import (
    BLOCKED_CONSECUTIVE_THRESHOLD,
    GoalStatus,
    get_goal_registry,
    reset_goal_registry_for_tests,
    set_goal,
)
from clawcodex_ext.goal.controller import GoalController
from clawcodex_ext.goal.tool import GoalTool
from src.tool_system.errors import ToolInputError
from clawcodex_ext.tool_system.protocol import ToolResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_goal_registry_for_tests()
    yield
    reset_goal_registry_for_tests()


@pytest.fixture(autouse=True)
def _install_fake_storage(monkeypatch):
    """Replace SessionStorage so persist_goal writes to memory."""
    class _FakeStorage:
        instances: dict = {}

        def __init__(self, session_id=None, **_: object) -> None:
            self.session_id = session_id or "fake"
            self.written = []
            type(self).instances[self.session_id] = self

        def write_raw(self, data):
            self.written.append(data)

        def flush(self):
            return None

        def read_transcript(self):
            return list(self.written)

    _FakeStorage.instances.clear()
    import src.services.session_storage as ss

    monkeypatch.setattr(ss, "SessionStorage", _FakeStorage)
    yield
    _FakeStorage.instances.clear()


def _ctx(session_id: Optional[str] = "tool-session") -> SimpleNamespace:
    return SimpleNamespace(
        session_id=session_id,
        workspace_root=None,
        cwd=None,
    )


def _call(input_data: dict, ctx=None) -> ToolResult:
    return GoalTool.call(input_data, ctx or _ctx())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_requires_action():
    schema = GoalTool.input_schema
    assert "action" in schema["required"]
    assert schema["properties"]["action"]["enum"] == ["get", "update"]
    assert "additionalProperties" in schema and schema["additionalProperties"] is False


def test_schema_rejects_budget_limited_in_status_enum():
    """``budget_limited`` and ``max_turns`` are controller-managed
    states — they must NOT appear in the model's settable enum."""
    status_enum = GoalTool.input_schema["properties"]["status"]["enum"]
    assert "budget_limited" not in status_enum
    assert "max_turns" not in status_enum


def test_is_read_only_for_get():
    assert GoalTool.is_read_only({"action": "get"}) is True


def test_is_read_only_false_for_update():
    assert GoalTool.is_read_only({"action": "update"}) is False


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_no_goal():
    result = _call({"action": "get"})
    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.output["hasGoal"] is False
    assert result.output["objective"] is None
    assert result.output["status"] is None


def test_get_with_active_goal():
    state = set_goal(None, "ship it", token_budget=500)
    get_goal_registry().set("tool-session", state)
    result = _call({"action": "get"})
    assert result.output["hasGoal"] is True
    assert result.output["objective"] == "ship it"
    assert result.output["status"] == "active"
    assert result.output["tokenBudget"] == 500
    assert result.output["tokensUsed"] == 0
    assert result.output["turnsExecuted"] == 0
    assert result.output["pill"].startswith("[Active")


def test_get_without_session_id_returns_no_goal():
    """A missing session id is treated as "no goal" rather than a crash."""
    result = _call({"action": "get"}, ctx=_ctx(session_id=None))
    assert result.output["hasGoal"] is False


# ---------------------------------------------------------------------------
# update — objective
# ---------------------------------------------------------------------------


def test_update_objective_replaces_goal():
    state = set_goal(None, "old", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    result = _call({"action": "update", "objective": "new"})
    assert result.is_error is False
    assert result.output["changed"] == "objective"
    stored = get_goal_registry().get("tool-session")
    assert stored.objective == "new"
    assert stored.status == GoalStatus.ACTIVE


def test_update_objective_rejects_empty_string():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    with pytest.raises(ToolInputError):
        _call({"action": "update", "objective": "   "})


def test_update_objective_rejects_too_long():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    long_text = "x" * 5000
    with pytest.raises(ToolInputError):
        _call({"action": "update", "objective": long_text})


def test_update_objective_requires_existing_goal():
    with pytest.raises(ToolInputError):
        _call({"action": "update", "objective": "new"})


# ---------------------------------------------------------------------------
# update — status transitions
# ---------------------------------------------------------------------------


def test_update_status_complete():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    result = _call({"action": "update", "status": "complete"})
    assert result.is_error is False
    assert result.output["newStatus"] == "complete"
    assert get_goal_registry().get("tool-session").status == GoalStatus.COMPLETE


def test_update_status_pause_then_resume():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    _call({"action": "update", "status": "paused"})
    assert get_goal_registry().get("tool-session").status == GoalStatus.PAUSED
    _call({"action": "update", "status": "active"})
    assert get_goal_registry().get("tool-session").status == GoalStatus.ACTIVE


def test_update_status_usage_limited():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    result = _call({"action": "update", "status": "usage_limited"})
    assert result.output["newStatus"] == "usage_limited"


def test_update_status_budget_limited_rejected():
    """The model must not be able to set budget_limited."""
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    with pytest.raises(ToolInputError):
        _call({"action": "update", "status": "budget_limited"})


def test_update_status_max_turns_rejected():
    with pytest.raises(ToolInputError):
        _call({"action": "update", "status": "max_turns"})


def test_update_status_blocked_requires_reason():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    with pytest.raises(ToolInputError):
        _call({"action": "update", "status": "blocked"})
    with pytest.raises(ToolInputError):
        _call({"action": "update", "status": "blocked", "reason": ""})


def test_update_status_blocked_uses_consecutive_counter():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    # First two reports: goal stays active, counter increments.
    _call({"action": "update", "status": "blocked", "reason": "no api"})
    assert get_goal_registry().get("tool-session").status == GoalStatus.ACTIVE
    _call({"action": "update", "status": "blocked", "reason": "no api"})
    assert get_goal_registry().get("tool-session").status == GoalStatus.ACTIVE
    # Third identical: flips to blocked.
    result = _call({"action": "update", "status": "blocked", "reason": "no api"})
    assert result.output["newStatus"] == "blocked"
    assert get_goal_registry().get("tool-session").status == GoalStatus.BLOCKED


def test_update_status_blocked_different_reason_resets_streak():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    for _ in range(BLOCKED_CONSECUTIVE_THRESHOLD - 1):
        _call({"action": "update", "status": "blocked", "reason": "no api"})
    # Different reason resets.
    _call({"action": "update", "status": "blocked", "reason": "compile error"})
    assert get_goal_registry().get("tool-session").status == GoalStatus.ACTIVE
    assert get_goal_registry().get("tool-session").blocked_attempts == 1


def test_update_status_invalid_value_rejected():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    with pytest.raises(ToolInputError):
        _call({"action": "update", "status": "not-a-status"})


def test_update_requires_either_objective_or_status():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    with pytest.raises(ToolInputError):
        _call({"action": "update"})


# ---------------------------------------------------------------------------
# update — invalid action
# ---------------------------------------------------------------------------


def test_unknown_action_raises():
    with pytest.raises(ToolInputError):
        _call({"action": "delete"})


def test_missing_action_raises():
    with pytest.raises(ToolInputError):
        _call({})


def test_non_string_action_raises():
    with pytest.raises(ToolInputError):
        _call({"action": 42})


# ---------------------------------------------------------------------------
# Persistence side-effects
# ---------------------------------------------------------------------------


def test_update_objective_writes_transcript_entry():
    state = set_goal(None, "old", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    _call({"action": "update", "objective": "new"})
    import src.services.session_storage as ss

    fake = ss.SessionStorage.instances.get("tool-session")  # type: ignore[attr-defined]
    assert fake is not None
    types = [entry.get("type") for entry in fake.written]
    assert "goal" in types


def test_complete_writes_transcript_entry():
    state = set_goal(None, "x", now_ms=1000)
    get_goal_registry().set("tool-session", state)
    _call({"action": "update", "status": "complete"})
    import src.services.session_storage as ss

    fake = ss.SessionStorage.instances.get("tool-session")  # type: ignore[attr-defined]
    assert any(e.get("type") == "goal" for e in fake.written)
