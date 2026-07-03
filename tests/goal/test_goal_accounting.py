"""Goal runtime accounting tests for F-122 Spec 5."""

from __future__ import annotations

from clawcodex_ext.goal.accounting import (
    BudgetLimitedGoalDisposition,
    GoalAccountingState,
    goal_token_delta_for_usage,
)
from clawcodex_ext.goal.model import ThreadGoalStatus


class FakeClock:
    def __init__(self) -> None:
        self._now = 1_000.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_goal_token_delta_matches_upstream_non_cached_input_plus_output() -> None:
    assert (
        goal_token_delta_for_usage(
            {
                "input_tokens": 100,
                "cache_read_input_tokens": 40,
                "output_tokens": 25,
                "reasoning_output_tokens": 99,
            }
        )
        == 85
    )


def test_goal_token_delta_falls_back_when_cached_input_is_unavailable() -> None:
    assert goal_token_delta_for_usage({"input_tokens": 12, "output_tokens": 8}) == 20


def test_progress_snapshot_tracks_expected_goal_id_and_avoids_double_counting() -> None:
    clock = FakeClock()
    accounting = GoalAccountingState(clock=clock)
    accounting.start_turn("turn-1", plan_mode=False)
    accounting.mark_turn_goal_active("turn-1", "goal-1")

    clock.advance(5)
    accounting.record_token_usage(
        "turn-1",
        {
            "input_tokens": 20,
            "cache_read_input_tokens": 5,
            "output_tokens": 7,
        },
    )

    snapshot = accounting.progress_snapshot("turn-1")

    assert snapshot is not None
    assert snapshot.expected_goal_id == "goal-1"
    assert snapshot.token_delta == 22
    assert snapshot.time_delta_seconds == 5

    accounting.mark_progress_accounted_for_status(
        "turn-1",
        snapshot,
        ThreadGoalStatus.ACTIVE,
        BudgetLimitedGoalDisposition.KEEP_ACTIVE,
    )

    assert accounting.progress_snapshot("turn-1") is None


def test_plan_mode_turns_do_not_account_goal_progress() -> None:
    accounting = GoalAccountingState()
    accounting.start_turn("turn-1", plan_mode=True)
    accounting.mark_turn_goal_active("turn-1", "goal-1")
    accounting.record_token_usage(
        "turn-1",
        {"input_tokens": 20, "output_tokens": 5},
    )

    assert accounting.progress_snapshot("turn-1") is None
