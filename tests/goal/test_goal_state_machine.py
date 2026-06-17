"""Unit tests for :mod:`clawcodex_ext.goal.state_machine`.

Covers every transition documented in
``docs/FEATURE_PLAN.md`` §2.6.2 plus the constraints from §2.6.3
(token tracking, blocked heuristic, max-turns reset, timing). All
timestamps are injected so the tests are deterministic.
"""

from __future__ import annotations

import pytest

from clawcodex_ext.goal.state_machine import (
    GoalObjectiveTooLong,
    GoalStateError,
    clear_goal,
    complete_goal,
    compute_active_elapsed_ms,
    continue_from_max_turns,
    mark_budget_limited,
    mark_usage_limited,
    pause_goal,
    record_blocker,
    resume_goal,
    set_goal,
    update_tokens,
)
from clawcodex_ext.goal.types import (
    BLOCKED_CONSECUTIVE_THRESHOLD,
    MAX_GOAL_TURNS,
    MAX_OBJECTIVE_CHARS,
    GoalState,
    GoalStatus,
)


# A monotonic clock used throughout the tests; the values are
# arbitrary as long as they advance.
T0 = 1_700_000_000_000  # ms
T1 = T0 + 60_000
T2 = T0 + 120_000
T3 = T0 + 180_000


def _active_goal(now_ms: int = T0, budget: int | None = 1000) -> GoalState:
    return set_goal(None, "实现一个 hello world", token_budget=budget, now_ms=now_ms)


# ---------------------------------------------------------------------------
# set_goal
# ---------------------------------------------------------------------------


def test_set_goal_from_none_creates_active_state():
    state = _active_goal()
    assert state.status == GoalStatus.ACTIVE
    assert state.objective == "实现一个 hello world"
    assert state.token_budget == 1000
    assert state.tokens_used == 0
    assert state.start_time_ms == T0
    assert state.accumulated_active_ms == 0
    assert state.blocked_attempts == 0
    assert state.turns_executed == 0


def test_set_goal_strips_whitespace():
    state = set_goal(None, "  trim me  ", now_ms=T0)
    assert state.objective == "trim me"


def test_set_goal_rejects_empty_objective():
    with pytest.raises(GoalStateError):
        set_goal(None, "   ", now_ms=T0)


def test_set_goal_rejects_objective_too_long():
    long_text = "x" * (MAX_OBJECTIVE_CHARS + 1)
    with pytest.raises(GoalObjectiveTooLong):
        set_goal(None, long_text, now_ms=T0)


def test_set_goal_accepts_max_length_objective():
    text = "y" * MAX_OBJECTIVE_CHARS
    state = set_goal(None, text, now_ms=T0)
    assert len(state.objective) == MAX_OBJECTIVE_CHARS


def test_set_goal_replaces_existing_resets_counters():
    old = _active_goal()
    new = set_goal(old, "新的目标", now_ms=T1)
    assert new.objective == "新的目标"
    assert new.status == GoalStatus.ACTIVE
    assert new.tokens_used == 0
    assert new.turns_executed == 0
    assert new.blocked_attempts == 0
    assert new.created_at_ms == old.created_at_ms


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------


def test_pause_goal_only_from_active():
    state = _active_goal()
    paused = pause_goal(state, now_ms=T1)
    assert paused.status == GoalStatus.PAUSED
    assert paused.paused_at_ms == T1
    # 60 s elapsed should be folded into accumulated_active_ms.
    assert paused.accumulated_active_ms == 60_000


def test_pause_goal_rejects_non_active():
    state = _active_goal()
    paused = pause_goal(state, now_ms=T1)
    with pytest.raises(GoalStateError):
        pause_goal(paused, now_ms=T2)


def test_resume_goal_from_paused_resets_blockers():
    state = _active_goal()
    state = record_blocker(state, "no API", now_ms=T1)[0]
    state = record_blocker(state, "no API", now_ms=T2)[0]
    assert state.blocked_attempts == 2

    paused = pause_goal(state, now_ms=T3)
    resumed = resume_goal(paused, now_ms=T3 + 30_000)
    assert resumed.status == GoalStatus.ACTIVE
    assert resumed.blocked_attempts == 0
    assert resumed.last_block_reason is None
    # accumulated_active_ms is preserved across pause/resume
    assert resumed.accumulated_active_ms == paused.accumulated_active_ms


def test_resume_goal_from_max_turns_does_not_reset_turns():
    state = _active_goal()
    max_state = GoalState(
        objective=state.objective,
        status=GoalStatus.MAX_TURNS,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=None,
        accumulated_active_ms=state.accumulated_active_ms,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=T1,
        turns_executed=MAX_GOAL_TURNS,
    )
    resumed = resume_goal(max_state, now_ms=T2)
    assert resumed.status == GoalStatus.ACTIVE
    assert resumed.turns_executed == MAX_GOAL_TURNS


def test_resume_rejects_other_states():
    state = _active_goal()
    with pytest.raises(GoalStateError):
        resume_goal(state, now_ms=T1)


# ---------------------------------------------------------------------------
# continue_from_max_turns
# ---------------------------------------------------------------------------


def test_continue_from_max_turns_resets_counter():
    state = _active_goal()
    max_state = GoalState(
        objective=state.objective,
        status=GoalStatus.MAX_TURNS,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=None,
        accumulated_active_ms=state.accumulated_active_ms,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=T1,
        turns_executed=MAX_GOAL_TURNS,
    )
    fresh = continue_from_max_turns(max_state, now_ms=T2)
    assert fresh.status == GoalStatus.ACTIVE
    assert fresh.turns_executed == 0
    assert fresh.start_time_ms == T2


def test_continue_rejects_non_max_turns():
    state = _active_goal()
    with pytest.raises(GoalStateError):
        continue_from_max_turns(state, now_ms=T1)


# ---------------------------------------------------------------------------
# complete / clear
# ---------------------------------------------------------------------------


def test_complete_goal_from_active_freezes_timer():
    state = _active_goal()
    completed = complete_goal(state, now_ms=T2)
    assert completed.status == GoalStatus.COMPLETE
    assert completed.accumulated_active_ms == 120_000
    assert completed.paused_at_ms is None


def test_complete_goal_is_idempotent():
    state = _active_goal()
    completed = complete_goal(state, now_ms=T1)
    again = complete_goal(completed, now_ms=T2)
    assert again.status == GoalStatus.COMPLETE
    # Idempotent — no time elapses on a no-op.
    assert again.accumulated_active_ms == completed.accumulated_active_ms


def test_complete_goal_rejects_terminal_states():
    state = _active_goal()
    blocked, _ = record_blocker(state, "x", now_ms=T1)
    blocked, _ = record_blocker(blocked, "x", now_ms=T2)
    blocked, _ = record_blocker(blocked, "x", now_ms=T3)
    with pytest.raises(GoalStateError):
        complete_goal(blocked, now_ms=T3)


def test_clear_goal_returns_none():
    assert clear_goal(_active_goal()) is None
    assert clear_goal(None) is None


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------


def test_update_tokens_accumulates():
    state = _active_goal(budget=100)
    state, crossed = update_tokens(state, 30, now_ms=T1)
    assert state.tokens_used == 30
    assert crossed is False

    state, crossed = update_tokens(state, 40, now_ms=T1)
    assert state.tokens_used == 70
    assert crossed is False


def test_update_tokens_signals_when_budget_crossed():
    state = _active_goal(budget=100)
    state, _ = update_tokens(state, 60, now_ms=T1)
    state, crossed = update_tokens(state, 50, now_ms=T2)
    assert state.tokens_used == 110
    assert crossed is True


def test_update_tokens_does_not_re_cross_after_first_crossing():
    state = _active_goal(budget=100)
    state, _ = update_tokens(state, 60, now_ms=T1)
    state, crossed1 = update_tokens(state, 50, now_ms=T2)
    assert crossed1 is True
    state, crossed2 = update_tokens(state, 100, now_ms=T3)
    assert crossed2 is False


def test_update_tokens_ignores_zero_or_negative_delta():
    state = _active_goal()
    state, crossed = update_tokens(state, 0, now_ms=T1)
    assert crossed is False
    assert state.tokens_used == 0


def test_update_tokens_no_budget_never_signals_crossing():
    state = _active_goal(budget=None)
    state, crossed = update_tokens(state, 10_000, now_ms=T1)
    assert crossed is False
    assert state.tokens_used == 10_000


def test_update_tokens_records_usage_when_paused():
    state = _active_goal()
    paused = pause_goal(state, now_ms=T1)
    paused_used, crossed = update_tokens(paused, 50, now_ms=T2)
    assert paused_used.tokens_used == 50
    assert crossed is False
    assert paused_used.status == GoalStatus.PAUSED


# ---------------------------------------------------------------------------
# Budget / usage limited transitions
# ---------------------------------------------------------------------------


def test_mark_budget_limited_flips_active_state():
    state = _active_goal()
    limited = mark_budget_limited(state, now_ms=T1)
    assert limited.status == GoalStatus.BUDGET_LIMITED
    assert limited.paused_at_ms is None


def test_mark_budget_limited_is_idempotent():
    state = _active_goal()
    once = mark_budget_limited(state, now_ms=T1)
    twice = mark_budget_limited(once, now_ms=T2)
    assert twice.status == GoalStatus.BUDGET_LIMITED
    assert twice.updated_at_ms == once.updated_at_ms


def test_mark_usage_limited_flips_active_state():
    state = _active_goal()
    limited = mark_usage_limited(state, now_ms=T1)
    assert limited.status == GoalStatus.USAGE_LIMITED


def test_mark_limited_rejects_non_active_states():
    state = _active_goal()
    paused = pause_goal(state, now_ms=T1)
    with pytest.raises(GoalStateError):
        mark_budget_limited(paused, now_ms=T2)
    with pytest.raises(GoalStateError):
        mark_usage_limited(paused, now_ms=T2)


# ---------------------------------------------------------------------------
# Blocked auditing
# ---------------------------------------------------------------------------


def test_record_blocker_first_time_starts_streak():
    state = _active_goal()
    new_state, transitioned = record_blocker(state, "rate limited", now_ms=T1)
    assert new_state.blocked_attempts == 1
    assert new_state.last_block_reason == "rate limited"
    assert transitioned is False
    assert new_state.status == GoalStatus.ACTIVE


def test_record_blocker_case_insensitive_match():
    state = _active_goal()
    state, _ = record_blocker(state, "Rate Limited", now_ms=T1)
    state, _ = record_blocker(state, "RATE LIMITED", now_ms=T2)
    state, transitioned = record_blocker(state, "rate limited", now_ms=T3)
    assert transitioned is True
    assert state.status == GoalStatus.BLOCKED


def test_record_blocker_different_reason_resets_streak():
    state = _active_goal()
    state, _ = record_blocker(state, "rate limited", now_ms=T1)
    state, _ = record_blocker(state, "rate limited", now_ms=T2)
    # Different reason → reset
    state, transitioned = record_blocker(state, "compile error", now_ms=T3)
    assert transitioned is False
    assert state.blocked_attempts == 1
    assert state.last_block_reason == "compile error"


def test_record_blocker_three_consecutive_flips_to_blocked():
    state = _active_goal()
    state, t1 = record_blocker(state, "no api", now_ms=T1)
    state, t2 = record_blocker(state, "no api", now_ms=T2)
    state, t3 = record_blocker(state, "no api", now_ms=T3)
    assert (t1, t2, t3) == (False, False, True)
    assert state.status == GoalStatus.BLOCKED
    assert state.blocked_attempts == 0
    assert state.last_block_reason is None


def test_record_blocker_respects_threshold_constant():
    """The threshold constant and the test both agree."""
    state = _active_goal()
    for i in range(BLOCKED_CONSECUTIVE_THRESHOLD - 1):
        state, _ = record_blocker(state, "stuck", now_ms=T1 + i * 1000)
    assert state.status == GoalStatus.ACTIVE
    state, transitioned = record_blocker(state, "stuck", now_ms=T1 + 10_000)
    assert transitioned is True
    assert state.status == GoalStatus.BLOCKED


def test_record_blocker_rejects_empty_reason():
    state = _active_goal()
    with pytest.raises(GoalStateError):
        record_blocker(state, "   ", now_ms=T1)


def test_record_blocker_noop_on_non_active():
    state = _active_goal()
    paused = pause_goal(state, now_ms=T1)
    new_state, transitioned = record_blocker(paused, "stuck", now_ms=T2)
    assert transitioned is False
    assert new_state is paused


# ---------------------------------------------------------------------------
# Timer math
# ---------------------------------------------------------------------------


def test_compute_active_elapsed_excludes_pause_time():
    state = _active_goal()  # start at T0
    state = pause_goal(state, now_ms=T1)  # +60s
    # 30 more seconds pass while paused.
    state = resume_goal(state, now_ms=T2)
    elapsed = compute_active_elapsed_ms(state, now_ms=T2 + 30_000)
    # Only the 60s before pause counts.
    assert elapsed == 60_000


def test_compute_active_elapsed_freezes_on_terminal():
    state = _active_goal()
    completed = complete_goal(state, now_ms=T2)
    # Even if ``now_ms`` advances, frozen at completion time.
    assert compute_active_elapsed_ms(completed, now_ms=T3) == 120_000


# ---------------------------------------------------------------------------
# GoalState round-trip
# ---------------------------------------------------------------------------


def test_goal_state_round_trip():
    original = _active_goal(budget=500)
    payload = original.to_dict()
    rebuilt = GoalState.from_dict(payload)
    assert rebuilt.objective == original.objective
    assert rebuilt.status == original.status
    assert rebuilt.token_budget == original.token_budget
    assert rebuilt.tokens_used == original.tokens_used
    assert rebuilt.start_time_ms == original.start_time_ms


def test_goal_state_is_terminal():
    assert GoalState(
        objective="x", status=GoalStatus.BLOCKED, start_time_ms=0,
        created_at_ms=0, updated_at_ms=0,
    ).is_terminal() is True
    assert GoalState(
        objective="x", status=GoalStatus.COMPLETE, start_time_ms=0,
        created_at_ms=0, updated_at_ms=0,
    ).is_terminal() is True
    assert GoalState(
        objective="x", status=GoalStatus.MAX_TURNS, start_time_ms=0,
        created_at_ms=0, updated_at_ms=0,
    ).is_terminal() is False


def test_goal_state_budget_remaining():
    state = _active_goal(budget=100)
    state, _ = update_tokens(state, 30, now_ms=T1)
    assert state.budget_remaining() == 70
    state, _ = update_tokens(state, 100, now_ms=T2)
    assert state.budget_remaining() == 0


def test_goal_state_budget_remaining_when_unbounded():
    state = _active_goal(budget=None)
    assert state.budget_remaining() is None
