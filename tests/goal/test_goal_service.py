"""GoalService parity tests for F-122 Spec 3."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from clawcodex_ext.feature_gate import get_registry, reset_registry
from clawcodex_ext.goal.gate import ensure_goals_feature_registered
from clawcodex_ext.goal.model import ThreadGoalStatus
from clawcodex_ext.goal.files import (
    GOAL_FILE_NAME,
    MAX_THREAD_GOAL_OBJECTIVE_CHARS,
    objective_text_for_edit,
)
from clawcodex_ext.goal.service import (
    GoalService,
    GoalServiceError,
    goal_thread_id_from_context,
)
from clawcodex_ext.goal.store import GoalStore, goals_db_filename


def make_service(tmp_path: Path, *, codex_home: Path | None = None) -> GoalService:
    return GoalService(
        store=GoalStore(tmp_path / goals_db_filename()),
        codex_home=codex_home,
    )


@pytest.fixture(autouse=True)
def _fresh_feature_registry():
    reset_registry()
    ensure_goals_feature_registered()
    yield
    reset_registry()


def test_set_goal_creates_active_goal_and_get_reads_it(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    goal = service.set_goal("thread-1", "ship spec 3")

    assert goal.thread_id == "thread-1"
    assert goal.objective == "ship spec 3"
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.tokens_used == 0
    assert service.get_goal("thread-1") == goal


def test_set_goal_materializes_long_objective_before_persisting(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    service = make_service(tmp_path, codex_home=codex_home)
    objective = "ship spec 6\n" + ("x" * MAX_THREAD_GOAL_OBJECTIVE_CHARS)

    goal = service.set_goal("thread-1", objective)

    assert goal.objective.startswith("Read the Codex goal objective file at ")
    assert objective_text_for_edit(goal.objective, codex_home=codex_home) == objective
    goal_files = list((codex_home / "attachments").glob(f"*/{GOAL_FILE_NAME}"))
    assert len(goal_files) == 1


def test_replace_goal_resets_usage_and_generates_new_goal_id(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    first = service.set_goal("thread-1", "old", token_budget=20)
    accounted = service.account_usage(
        "thread-1",
        expected_goal_id=first.goal_id,
        token_delta=12,
        elapsed_seconds=5,
    )

    replacement = service.replace_goal("thread-1", "new")

    assert accounted is not None
    assert replacement.goal_id != first.goal_id
    assert replacement.objective == "new"
    assert replacement.tokens_used == 0
    assert replacement.time_used_seconds == 0
    assert replacement.status is ThreadGoalStatus.ACTIVE


def test_update_goal_uses_expected_goal_id_for_cas(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    stale = service.set_goal("thread-1", "old")
    current = service.replace_goal("thread-1", "new")

    result = service.update_goal(
        "thread-1",
        ThreadGoalStatus.COMPLETE,
        expected_goal_id=stale.goal_id,
    )

    assert result is None
    assert service.get_goal("thread-1") == current


def test_pause_and_resume_go_through_status_updates(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.set_goal("thread-1", "pause me")

    paused = service.pause_goal("thread-1")
    resumed = service.resume_goal("thread-1")

    assert paused is not None
    assert paused.status is ThreadGoalStatus.PAUSED
    assert resumed is not None
    assert resumed.status is ThreadGoalStatus.ACTIVE


def test_goal_thread_id_prefers_explicit_context_over_tool_session() -> None:
    context = SimpleNamespace(
        goal_thread_id="explicit-thread",
        tool_context=SimpleNamespace(session_id="tool-session"),
    )

    assert goal_thread_id_from_context(context) == "explicit-thread"


def test_goal_thread_id_falls_back_to_tool_context_session() -> None:
    context = SimpleNamespace(tool_context=SimpleNamespace(session_id="tool-session"))

    assert goal_thread_id_from_context(context) == "tool-session"


def test_resume_budget_limited_goal_stays_limited_while_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    goal = service.set_goal("thread-1", "budget", token_budget=10)
    limited = service.account_usage(
        "thread-1",
        expected_goal_id=goal.goal_id,
        token_delta=10,
        elapsed_seconds=1,
    )

    resumed = service.resume_goal("thread-1")

    assert limited is not None
    assert limited.status is ThreadGoalStatus.BUDGET_LIMITED
    assert resumed is not None
    assert resumed.status is ThreadGoalStatus.BUDGET_LIMITED


def test_clear_goal_returns_boolean_and_removes_goal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.set_goal("thread-1", "clear me")

    assert service.clear_goal("thread-1") is True
    assert service.get_goal("thread-1") is None
    assert service.clear_goal("thread-1") is False


def test_service_rejects_all_operations_when_goal_feature_disabled(tmp_path: Path) -> None:
    ensure_goals_feature_registered()
    get_registry().set_override("goals", False)
    service = make_service(tmp_path)

    with pytest.raises(GoalServiceError, match="goals feature is disabled"):
        service.set_goal("thread-1", "nope")

    with pytest.raises(GoalServiceError, match="goals feature is disabled"):
        service.get_goal("thread-1")


def test_service_rejects_empty_objective_and_negative_budget(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    with pytest.raises(GoalServiceError, match="goal objective cannot be empty"):
        service.create_goal("thread-1", "  ")

    with pytest.raises(GoalServiceError, match="token budget must be non-negative"):
        service.create_goal("thread-1", "negative budget", token_budget=-1)
