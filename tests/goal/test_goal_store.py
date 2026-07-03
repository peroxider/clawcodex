"""SQLite GoalStore parity tests for F-122 Spec 2."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from clawcodex_ext.goal.model import ThreadGoalStatus
from clawcodex_ext.goal.store import (
    GoalStore,
    GoalUpdate,
    current_goal_thread_id,
    goals_db_filename,
    goals_db_path,
)
from src.bootstrap.state import SessionId, reset_state_for_tests, switch_session


def make_store(tmp_path: Path) -> GoalStore:
    return GoalStore(tmp_path / goals_db_filename())


def test_goals_db_path_uses_independent_goal_store_file(tmp_path: Path) -> None:
    assert goals_db_filename() == "goals_1.sqlite"
    assert goals_db_path(home=tmp_path) == tmp_path / ".clawcodex" / "goals_1.sqlite"


def test_current_goal_thread_id_uses_recoverable_bootstrap_session_id() -> None:
    reset_state_for_tests()
    switch_session(SessionId("session-123"))

    assert current_goal_thread_id() == "session-123"


def test_schema_bootstrap_matches_upstream_columns_and_constraints(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.close()

    with sqlite3.connect(tmp_path / goals_db_filename()) as conn:
        columns = conn.execute("PRAGMA table_info(thread_goals)").fetchall()
        create_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'thread_goals'"
        ).fetchone()[0]
    completed_field = "completed" + "_at"

    assert [column[1] for column in columns] == [
        "thread_id",
        "goal_id",
        "objective",
        "status",
        "token_budget",
        "tokens_used",
        "time_used_seconds",
        "created_at_ms",
        "updated_at_ms",
    ]
    assert columns[0][5] == 1
    assert completed_field not in create_sql
    for status in ThreadGoalStatus:
        assert f"'{status.value}'" in create_sql
    assert "tokens_used INTEGER NOT NULL DEFAULT 0" in create_sql
    assert "time_used_seconds INTEGER NOT NULL DEFAULT 0" in create_sql


def test_insert_rejects_unfinished_goal_but_allows_after_complete(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    first = store.insert_thread_goal(
        "thread-1",
        "first objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=100,
    )
    duplicate = store.insert_thread_goal(
        "thread-1",
        "second objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=200,
    )
    assert duplicate is None
    assert store.get_thread_goal("thread-1") == first

    completed = store.update_thread_goal(
        "thread-1",
        GoalUpdate(status=ThreadGoalStatus.COMPLETE),
        expected_goal_id=first.goal_id,
    )
    replacement = store.insert_thread_goal(
        "thread-1",
        "second objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=200,
    )

    assert completed is not None
    assert replacement.goal_id != first.goal_id
    assert replacement.objective == "second objective"
    assert replacement.tokens_used == 0
    assert replacement.time_used_seconds == 0


def test_replace_unconditionally_resets_usage_and_generates_new_goal_id(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    first = store.replace_thread_goal(
        "thread-1",
        "first objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=100,
    )
    accounted = store.account_thread_goal_usage("thread-1", time_delta=5, token_delta=60)
    second = store.replace_thread_goal(
        "thread-1",
        "second objective",
        ThreadGoalStatus.PAUSED,
        token_budget=None,
    )

    assert accounted is not None
    assert accounted.tokens_used == 60
    assert second.goal_id != first.goal_id
    assert second.objective == "second objective"
    assert second.status is ThreadGoalStatus.PAUSED
    assert second.token_budget is None
    assert second.tokens_used == 0
    assert second.time_used_seconds == 0


def test_update_expected_goal_id_prevents_stale_writes(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    original = store.replace_thread_goal(
        "thread-1",
        "old objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=100,
    )
    current = store.replace_thread_goal(
        "thread-1",
        "new objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=200,
    )

    stale = store.update_thread_goal(
        "thread-1",
        GoalUpdate(status=ThreadGoalStatus.COMPLETE, token_budget=50),
        expected_goal_id=original.goal_id,
    )
    fresh = store.get_thread_goal("thread-1")

    assert stale is None
    assert fresh == current


def test_account_usage_expected_goal_id_prevents_stale_usage_and_budget_status(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)

    original = store.replace_thread_goal(
        "thread-1",
        "old objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=10,
    )
    current = store.replace_thread_goal(
        "thread-1",
        "new objective",
        ThreadGoalStatus.ACTIVE,
        token_budget=10,
    )

    stale = store.account_thread_goal_usage(
        "thread-1",
        time_delta=5,
        token_delta=10,
        expected_goal_id=original.goal_id,
    )

    assert stale is None
    assert store.get_thread_goal("thread-1") == current


def test_account_usage_accumulates_and_budget_limits_active_goal(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.replace_thread_goal(
        "thread-1",
        "stay within budget",
        ThreadGoalStatus.ACTIVE,
        token_budget=20,
    )

    first = store.account_thread_goal_usage("thread-1", time_delta=7, token_delta=5)
    second = store.account_thread_goal_usage("thread-1", time_delta=3, token_delta=15)

    assert first is not None
    assert first.status is ThreadGoalStatus.ACTIVE
    assert first.tokens_used == 5
    assert first.time_used_seconds == 7
    assert second is not None
    assert second.status is ThreadGoalStatus.BUDGET_LIMITED
    assert second.tokens_used == 20
    assert second.time_used_seconds == 10


def test_zero_budget_active_goal_is_budget_limited_on_create(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    goal = store.insert_thread_goal(
        "thread-1",
        "zero budget",
        ThreadGoalStatus.ACTIVE,
        token_budget=0,
    )

    assert goal.status is ThreadGoalStatus.BUDGET_LIMITED
    assert goal.tokens_used == 0
    assert goal.time_used_seconds == 0


def test_store_recovers_goal_from_new_instance(tmp_path: Path) -> None:
    db_path = tmp_path / goals_db_filename()
    first_store = GoalStore(db_path)
    goal = first_store.replace_thread_goal(
        "thread-1",
        "persist me",
        ThreadGoalStatus.ACTIVE,
        token_budget=100,
    )
    first_store.close()

    second_store = GoalStore(db_path)

    assert second_store.get_thread_goal("thread-1") == goal


def test_delete_thread_goal_removes_only_that_thread(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.replace_thread_goal(
        "thread-1",
        "delete me",
        ThreadGoalStatus.ACTIVE,
        token_budget=None,
    )
    second = store.replace_thread_goal(
        "thread-2",
        "keep me",
        ThreadGoalStatus.ACTIVE,
        token_budget=None,
    )

    deleted = store.delete_thread_goal("thread-1")

    assert deleted == first
    assert store.get_thread_goal("thread-1") is None
    assert store.get_thread_goal("thread-2") == second
