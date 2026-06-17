"""Unit tests for :class:`clawcodex_ext.goal.controller.GoalController`."""

from __future__ import annotations

import pytest

from clawcodex_ext.goal import (
    MAX_GOAL_TURNS,
    GoalState,
    GoalStatus,
    get_goal_registry,
    reset_goal_registry_for_tests,
    set_goal,
)
from clawcodex_ext.goal.controller import GoalController


T0 = 1_700_000_000_000


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Ensure each test starts with a fresh process singleton."""
    reset_goal_registry_for_tests()
    yield
    reset_goal_registry_for_tests()


# ---------------------------------------------------------------------------
# Binding / state
# ---------------------------------------------------------------------------


def test_controller_without_session_id_is_noop():
    ctrl = GoalController()
    assert ctrl.get_state() is None
    # No crash.
    assert ctrl.on_assistant_turn_complete() is None


def test_controller_bind_uses_session_registry():
    ctrl = GoalController()
    ctrl.bind("sess-1")
    # No goal yet — but binding works.
    assert ctrl.get_state() is None


def test_set_new_goal_persists_and_broadcasts():
    """set_new_goal should hit the registry and queue meta + steering prompts."""
    ctrl = GoalController("sess-1")
    state = ctrl.set_new_goal("ship it", token_budget=500)
    assert state.status == GoalStatus.ACTIVE
    assert state.token_budget == 500

    stored = get_goal_registry().get("sess-1")
    assert stored is state

    metas = ctrl.drain_pending_meta_messages()
    assert any("ship it" in m for m in metas)
    inj = ctrl.drain_pending_injection()
    assert inj is not None
    assert inj["kind"] == "objective_updated"


def test_set_new_goal_rejects_too_long_objective():
    ctrl = GoalController("sess-1")
    with pytest.raises(Exception):
        ctrl.set_new_goal("x" * (4001))


def test_set_new_goal_replaces_existing():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("first")
    ctrl.set_new_goal("second")
    state = ctrl.get_state()
    assert state.objective == "second"
    assert state.turns_executed == 0
    assert state.tokens_used == 0


# ---------------------------------------------------------------------------
# on_assistant_turn_complete
# ---------------------------------------------------------------------------


def test_on_assistant_turn_complete_no_goal_is_noop():
    ctrl = GoalController("sess-1")
    assert ctrl.on_assistant_turn_complete() is None


def test_on_assistant_turn_complete_active_injects_continuation():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    # First meta injection is from set_new_goal; drain it.
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    inj = ctrl.on_assistant_turn_complete()
    assert inj is not None
    assert inj["kind"] == "continuation"
    assert "ship it" in inj["text"]
    # turns_executed incremented.
    assert ctrl.get_state().turns_executed == 1


def test_paused_goal_does_not_inject():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    ctrl.pause()
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    assert ctrl.on_assistant_turn_complete() is None


def test_aborted_turn_skips_injection():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    ctrl.mark_aborted()
    assert ctrl.on_assistant_turn_complete() is None
    # And the flag is reset for the next call.
    inj = ctrl.on_assistant_turn_complete()
    assert inj is not None  # active again next turn


def test_plan_mode_suppresses_injection():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    ctrl.set_plan_mode(True)
    assert ctrl.on_assistant_turn_complete() is None
    ctrl.set_plan_mode(False)
    assert ctrl.on_assistant_turn_complete() is not None


def test_budget_limited_does_not_inject():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=100)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    # Force the goal into budget_limited.
    ctrl.mark_usage_limited()
    # mark_usage_limited doesn't flip to budget_limited; do it via record_usage.
    ctrl.resume()  # back to active
    # Now exhaust the budget.
    ctrl.record_usage({
        "input_tokens": 60, "output_tokens": 60,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    })
    # After budget crossing, state should be budget_limited.
    assert ctrl.get_state().status == GoalStatus.BUDGET_LIMITED
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    assert ctrl.on_assistant_turn_complete() is None


def test_max_turns_stops_injection():
    """When turns_executed reaches MAX_GOAL_TURNS, the goal flips to
    MAX_TURNS and no further continuation is queued."""
    ctrl = GoalController("sess-1")
    state = set_goal(None, "long task", now_ms=T0)
    get_goal_registry().set("sess-1", state)

    # Fire ``MAX_GOAL_TURNS - 1`` completions; the last should flip to MAX_TURNS.
    last_inj = None
    for i in range(MAX_GOAL_TURNS):
        last_inj = ctrl.on_assistant_turn_complete()
        ctrl.drain_pending_injection()
    # Final call returned None because the goal just hit MAX_TURNS.
    assert last_inj is None
    assert ctrl.get_state().status == GoalStatus.MAX_TURNS

    # Subsequent calls do nothing.
    assert ctrl.on_assistant_turn_complete() is None


def test_continue_from_max_turns_allows_injection_again():
    ctrl = GoalController("sess-1")
    get_goal_registry().set(
        "sess-1",
        GoalState(
            objective="long task",
            status=GoalStatus.MAX_TURNS,
            start_time_ms=T0,
            created_at_ms=T0,
            updated_at_ms=T0,
            turns_executed=MAX_GOAL_TURNS,
        ),
    )
    ctrl.continue_from_max_turns()
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    inj = ctrl.on_assistant_turn_complete()
    assert inj is not None
    assert ctrl.get_state().turns_executed == 1


# ---------------------------------------------------------------------------
# record_usage (token hook)
# ---------------------------------------------------------------------------


def test_record_usage_zero_or_empty_is_noop():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=100)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    assert ctrl.record_usage({}) is None
    assert ctrl.record_usage({"input_tokens": 0, "output_tokens": 0}) is None


def test_record_usage_accumulates_tokens():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=1000)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    ctrl.record_usage({"input_tokens": 30, "output_tokens": 20})
    assert ctrl.get_state().tokens_used == 50
    # No injection yet.
    assert ctrl.record_usage({"input_tokens": 30, "output_tokens": 20}) is None
    assert ctrl.get_state().tokens_used == 100


def test_record_usage_includes_cache_tokens():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=1000)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    ctrl.record_usage({
        "input_tokens": 10,
        "output_tokens": 10,
        "cache_read_input_tokens": 5,
        "cache_creation_input_tokens": 5,
    })
    assert ctrl.get_state().tokens_used == 30


def test_record_usage_crossing_budget_returns_one_shot_wrapup():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=100)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    inj1 = ctrl.record_usage({"input_tokens": 60, "output_tokens": 0})
    assert inj1 is None

    inj2 = ctrl.record_usage({"input_tokens": 0, "output_tokens": 60})
    assert inj2 is not None
    assert inj2["kind"] == "budget_limit"
    assert "ship it" in inj2["text"]
    # State flipped to budget_limited.
    assert ctrl.get_state().status == GoalStatus.BUDGET_LIMITED

    # One-shot — second crossing does NOT re-queue the wrap-up.
    inj3 = ctrl.record_usage({"input_tokens": 50, "output_tokens": 50})
    assert inj3 is None


def test_record_usage_no_budget_never_triggers_wrapup():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")  # no budget
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    for _ in range(5):
        assert ctrl.record_usage({"input_tokens": 100, "output_tokens": 100}) is None
    assert ctrl.get_state().status == GoalStatus.ACTIVE


def test_record_usage_non_dict_is_noop():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    assert ctrl.record_usage("not a dict") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# pause / resume / clear / complete
# ---------------------------------------------------------------------------


def test_pause_and_resume_round_trip():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=500)
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    assert ctrl.pause().status == GoalStatus.PAUSED
    resumed = ctrl.resume()
    assert resumed.status == GoalStatus.ACTIVE
    # resumed state has blocked_attempts reset.
    assert resumed.blocked_attempts == 0


def test_complete_is_terminal():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()
    completed = ctrl.complete()
    assert completed.status == GoalStatus.COMPLETE
    # No further injections.
    assert ctrl.on_assistant_turn_complete() is None


def test_clear_writes_tombstone_and_drops_state():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    ctrl.clear()
    assert ctrl.get_state() is None
    metas = ctrl.drain_pending_meta_messages()
    assert any("cleared" in m for m in metas)


def test_record_blocker_no_transition_does_not_inject():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    state, transitioned = ctrl.record_blocker("stuck")
    assert transitioned is False
    assert state.status == GoalStatus.ACTIVE


def test_record_blocker_three_streak_flips_to_blocked():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it")
    ctrl.drain_pending_meta_messages()
    ctrl.drain_pending_injection()

    ctrl.record_blocker("stuck")
    ctrl.record_blocker("stuck")
    _, transitioned = ctrl.record_blocker("stuck")
    assert transitioned is True
    assert ctrl.get_state().status == GoalStatus.BLOCKED


# ---------------------------------------------------------------------------
# UI pill
# ---------------------------------------------------------------------------


def test_get_pill_state_returns_none_when_no_goal():
    ctrl = GoalController("sess-1")
    assert ctrl.get_pill_state() is None


def test_get_pill_state_returns_dict_for_active_goal():
    ctrl = GoalController("sess-1")
    ctrl.set_new_goal("ship it", token_budget=500)
    pill = ctrl.get_pill_state()
    assert pill is not None
    assert pill["status"] == "active"
    assert pill["objective"] == "ship it"
    assert pill["tokens_used"] == 0
    assert pill["token_budget"] == 500
    assert pill["turns_executed"] == 0
    assert pill["pill"].startswith("[Active")
