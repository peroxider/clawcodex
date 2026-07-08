"""Thread goal protocol facade tests for F-122 Spec 3."""

from __future__ import annotations

from pathlib import Path

import pytest

from clawcodex_ext.feature_gate import get_registry, reset_registry
from clawcodex_ext.goal.gate import ensure_goals_feature_registered
from clawcodex_ext.goal.model import ThreadGoalStatus
from clawcodex_ext.goal.protocol import (
    GoalEventLog,
    ThreadGoalClearParams,
    ThreadGoalGetParams,
    ThreadGoalProtocol,
    ThreadGoalSetParams,
)
from clawcodex_ext.goal.service import GoalService, GoalServiceError
from clawcodex_ext.goal.store import GoalStore, goals_db_filename


def make_protocol(tmp_path: Path) -> tuple[ThreadGoalProtocol, GoalEventLog]:
    events = GoalEventLog()
    service = GoalService(store=GoalStore(tmp_path / goals_db_filename()))
    return ThreadGoalProtocol(service=service, events=events), events


@pytest.fixture(autouse=True)
def _fresh_feature_registry():
    reset_registry()
    ensure_goals_feature_registered()
    yield
    reset_registry()


def test_thread_goal_set_returns_response_then_updated_notification(
    tmp_path: Path,
) -> None:
    protocol, events = make_protocol(tmp_path)

    response = protocol.thread_goal_set(
        ThreadGoalSetParams(thread_id="thread-1", objective="ship it")
    )

    assert response.goal.objective == "ship it"
    assert response.goal.status is ThreadGoalStatus.ACTIVE
    assert [message.kind for message in events.messages] == ["response", "notification"]
    assert [message.method for message in events.messages] == [
        "thread/goal/set",
        "thread/goal/updated",
    ]
    assert events.messages[1].payload.turn_id is None
    assert events.messages[1].payload.goal == response.goal
    assert "goalId" not in response.goal.to_dict()


def test_thread_goal_get_returns_goal_without_emitting_notifications(
    tmp_path: Path,
) -> None:
    protocol, events = make_protocol(tmp_path)
    protocol.thread_goal_set(ThreadGoalSetParams(thread_id="thread-1", objective="read me"))
    events.clear()

    response = protocol.thread_goal_get(ThreadGoalGetParams(thread_id="thread-1"))

    assert response.goal is not None
    assert response.goal.objective == "read me"
    assert [message.method for message in events.messages] == ["thread/goal/get"]


def test_thread_goal_clear_returns_response_then_cleared_notification(
    tmp_path: Path,
) -> None:
    protocol, events = make_protocol(tmp_path)
    protocol.thread_goal_set(ThreadGoalSetParams(thread_id="thread-1", objective="delete me"))
    events.clear()

    response = protocol.thread_goal_clear(ThreadGoalClearParams(thread_id="thread-1"))

    assert response.cleared is True
    assert [message.kind for message in events.messages] == ["response", "notification"]
    assert [message.method for message in events.messages] == [
        "thread/goal/clear",
        "thread/goal/cleared",
    ]
    assert events.messages[1].payload.thread_id == "thread-1"


def test_thread_goal_clear_without_goal_emits_only_response(tmp_path: Path) -> None:
    protocol, events = make_protocol(tmp_path)

    response = protocol.thread_goal_clear(ThreadGoalClearParams(thread_id="thread-1"))

    assert response.cleared is False
    assert [message.method for message in events.messages] == ["thread/goal/clear"]


def test_thread_goal_set_can_update_status_without_changing_objective(
    tmp_path: Path,
) -> None:
    protocol, _events = make_protocol(tmp_path)
    created = protocol.thread_goal_set(
        ThreadGoalSetParams(thread_id="thread-1", objective="pause me")
    ).goal

    paused = protocol.thread_goal_set(
        ThreadGoalSetParams(thread_id="thread-1", status=ThreadGoalStatus.PAUSED)
    ).goal

    assert paused.objective == created.objective
    assert paused.status is ThreadGoalStatus.PAUSED


def test_disabled_protocol_rejects_request_and_emits_no_messages(tmp_path: Path) -> None:
    protocol, events = make_protocol(tmp_path)
    get_registry().set_override("goals", False)

    with pytest.raises(GoalServiceError, match="goals feature is disabled"):
        protocol.thread_goal_set(ThreadGoalSetParams(thread_id="thread-1", objective="nope"))

    assert events.messages == []
