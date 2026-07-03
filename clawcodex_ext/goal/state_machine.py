"""Pure-function state transitions for :class:`GoalState`.

Every transition returns a *new* :class:`GoalState` — the dataclass
is never mutated in place, so callers can rely on snapshot semantics
when diffing for persistence or auditing. The functions deliberately
take ``now_ms`` as a parameter rather than calling
``time.time()`` internally: this keeps the transitions testable
and lets the controller inject a single monotonic timestamp for an
entire transition batch (no clock skew between successive fields).
"""

from __future__ import annotations

from typing import Any, Optional

from .types import (
    BLOCKED_CONSECUTIVE_THRESHOLD,
    MAX_GOAL_TURNS,
    MAX_OBJECTIVE_CHARS,
    MILESTONE_TURN_INTERVAL,
    GoalState,
    GoalStatus,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GoalStateError(ValueError):
    """Raised when a transition would violate the state machine."""


class GoalObjectiveTooLong(ValueError):
    """Raised when an objective exceeds :data:`MAX_OBJECTIVE_CHARS`."""

    def __init__(self, length: int, max_length: int = MAX_OBJECTIVE_CHARS) -> None:
        super().__init__(
            f"objective is {length} chars; max is {max_length}. "
            "Write the detail to a file and reference it with a short summary."
        )
        self.length = length
        self.max_length = max_length


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def compute_active_elapsed_ms(state: GoalState, now_ms: int) -> int:
    """Return how many ms ``state`` has spent in active-or-terminal.

    Pause time is excluded by construction: :func:`pause_goal`
    freezes the active elapsed into ``accumulated_active_ms`` at the
    pause moment, :func:`resume_goal` keeps the field untouched, and
    :func:`complete_goal` / :func:`mark_budget_limited` etc. fold
    the run-up delta in before the status change. The ``now_ms``
    argument is therefore redundant — kept for API symmetry with the
    transition functions and to make future "live tick" behavior a
    single-line change.
    """
    return state.accumulated_active_ms


def _now_ms(now_ms: Optional[int] = None) -> int:
    """Resolve ``now_ms`` to a wall-clock millisecond timestamp.

    When ``now_ms`` is ``None`` (the common case at runtime) we read
    the system clock. Tests pass an explicit value to keep results
    deterministic.
    """
    if now_ms is not None:
        return int(now_ms)
    import time

    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def set_goal(
    state: Optional[GoalState],
    objective: str,
    *,
    token_budget: Optional[int] = None,
    now_ms: Optional[int] = None,
) -> GoalState:
    """Replace ``state`` (or create) with a fresh active goal.

    The previous state, if any, is discarded — the caller is
    responsible for confirming with the user that they want to
    overwrite an in-flight goal (see
    :class:`clawcodex_ext.goal.command.GoalCommand`).
    """
    text = (objective or "").strip()
    if not text:
        raise GoalStateError("objective must be a non-empty string")
    if len(text) > MAX_OBJECTIVE_CHARS:
        raise GoalObjectiveTooLong(len(text), MAX_OBJECTIVE_CHARS)
    now = _now_ms(now_ms)
    return GoalState(
        objective=text,
        status=GoalStatus.ACTIVE,
        token_budget=token_budget,
        tokens_used=0,
        start_time_ms=now,
        paused_at_ms=None,
        accumulated_active_ms=0,
        blocked_attempts=0,
        last_block_reason=None,
        created_at_ms=state.created_at_ms if state is not None else now,
        updated_at_ms=now,
        turns_executed=0,
        # Fresh goal — clear any accumulated milestones
        milestones=[],
    )


def pause_goal(state: GoalState, *, now_ms: Optional[int] = None) -> GoalState:
    """Move an ``active`` goal into ``paused``.

    Pausing records ``paused_at_ms`` and folds any in-progress
    active ms into ``accumulated_active_ms`` so the timer resumes
    cleanly on ``resume_goal``.
    """
    if state.status != GoalStatus.ACTIVE:
        raise GoalStateError(
            f"cannot pause goal in status {state.status.value!r} (only active)"
        )
    now = _now_ms(now_ms)
    elapsed = max(0, now - state.start_time_ms)
    return GoalState(
        objective=state.objective,
        status=GoalStatus.PAUSED,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=now,
        accumulated_active_ms=state.accumulated_active_ms + elapsed,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
    )


def resume_goal(state: GoalState, *, now_ms: Optional[int] = None) -> GoalState:
    """Move a ``paused``, ``max_turns``, or ``usage_limited`` goal
    back to ``active``.

    ``blocked_attempts`` and ``last_block_reason`` are reset, matching
    FEATURE_PLAN.md §2.6.1 ("resume 重置 blockedAttempts"). When
    resuming from ``max_turns`` the counter stays where ``continue``
    left it; ``resume`` does not reset ``turns_executed``.
    """
    if state.status not in (
        GoalStatus.PAUSED,
        GoalStatus.MAX_TURNS,
        GoalStatus.USAGE_LIMITED,
    ):
        raise GoalStateError(
            f"cannot resume goal in status {state.status.value!r} "
            "(only paused, max_turns, or usage_limited)"
        )
    now = _now_ms(now_ms)
    return GoalState(
        objective=state.objective,
        status=GoalStatus.ACTIVE,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=now,
        paused_at_ms=None,
        accumulated_active_ms=state.accumulated_active_ms,
        blocked_attempts=0,
        last_block_reason=None,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
    )


def increment_turns(
    state: GoalState,
    max_turns: int = MAX_GOAL_TURNS,
    *,
    now_ms: Optional[int] = None,
) -> tuple[GoalState, bool]:
    """Bump ``turns_executed``; flip to ``MAX_TURNS`` if the cap is hit.

    Returns ``(new_state, hit_max)`` where ``hit_max`` is ``True`` on
    the exact transition ``MAX_GOAL_TURNS - 1 -> MAX_GOAL_TURNS``. The
    caller uses the flag to suppress the next continuation injection
    and surface a ``/goal continue`` hint to the user.
    """
    if state.status != GoalStatus.ACTIVE:
        return state, False
    new_turns = state.turns_executed + 1
    hit_max = new_turns >= max_turns and state.turns_executed < max_turns
    new_status = GoalStatus.MAX_TURNS if hit_max else GoalStatus.ACTIVE
    now = _now_ms(now_ms)
    accumulated = state.accumulated_active_ms
    if hit_max:
        accumulated += max(0, now - state.start_time_ms)
    return (
        GoalState(
            objective=state.objective,
            status=new_status,
            token_budget=state.token_budget,
            tokens_used=state.tokens_used,
            start_time_ms=state.start_time_ms,
            paused_at_ms=state.paused_at_ms,
            accumulated_active_ms=accumulated,
            blocked_attempts=state.blocked_attempts,
            last_block_reason=state.last_block_reason,
            created_at_ms=state.created_at_ms,
            updated_at_ms=now,
            turns_executed=min(new_turns, max_turns),
            milestones=list(state.milestones),
        ),
        hit_max,
    )


def add_milestone(
    state: GoalState,
    summary: str,
    *,
    now_ms: Optional[int] = None,
    max_milestones: int = 10,
) -> GoalState:
    """Record a progressive-summary milestone for the current turn.

    Appends a ``{"turn": …, "tokens_used": …, "summary": …}`` entry to
    ``state.milestones``.  Old entries beyond ``max_milestones`` are
    pruned (oldest first) so the list never grows unbounded.

    Returns a new ``GoalState`` with the appended milestone.
    """
    now = _now_ms(now_ms)
    entry: dict[str, Any] = {
        "turn": state.turns_executed,
        "tokens_used": state.tokens_used,
        "summary": (summary or "").strip(),
    }
    pruned = (list(state.milestones) + [entry])[-max_milestones:]
    return GoalState(
        objective=state.objective,
        status=state.status,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=state.paused_at_ms,
        accumulated_active_ms=state.accumulated_active_ms,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
        milestones=pruned,
    )


def continue_from_max_turns(
    state: GoalState, *, now_ms: Optional[int] = None
) -> GoalState:
    """Reset the ``turns_executed`` counter on a ``max_turns`` goal.

    Unlike :func:`resume_goal`, this does NOT change the status —
    the goal stays in ``active`` (the controller decides that).
    Instead it returns an updated state the controller can merge
    once it has flipped the status to ACTIVE.
    """
    if state.status != GoalStatus.MAX_TURNS:
        raise GoalStateError(
            f"cannot continue goal in status {state.status.value!r} "
            "(only max_turns)"
        )
    now = _now_ms(now_ms)
    return GoalState(
        objective=state.objective,
        status=GoalStatus.ACTIVE,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=now,
        paused_at_ms=None,
        accumulated_active_ms=state.accumulated_active_ms,
        blocked_attempts=0,
        last_block_reason=None,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=0,
    )


def complete_goal(state: GoalState, *, now_ms: Optional[int] = None) -> GoalState:
    """Mark the goal as completed by the user.

    Valid from any non-terminal-but-still-actionable state
    (active/paused/max_turns). Returns a state with
    ``status == COMPLETE``.
    """
    if state.status == GoalStatus.COMPLETE:
        # Idempotent.
        return state
    if state.status not in (
        GoalStatus.ACTIVE,
        GoalStatus.PAUSED,
        GoalStatus.MAX_TURNS,
    ):
        raise GoalStateError(
            f"cannot complete goal in status {state.status.value!r}"
        )
    now = _now_ms(now_ms)
    accumulated = state.accumulated_active_ms
    if state.status == GoalStatus.ACTIVE and state.start_time_ms > 0:
        accumulated += max(0, now - state.start_time_ms)
    return GoalState(
        objective=state.objective,
        status=GoalStatus.COMPLETE,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=None,
        accumulated_active_ms=accumulated,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
    )


def clear_goal(state: Optional[GoalState]) -> None:
    """Remove a goal. Always returns ``None``.

    The controller is expected to call this on the registry rather
    than passing a state; this function exists for symmetry / tests.
    """
    return None


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------


def update_tokens(
    state: GoalState,
    delta_tokens: int,
    *,
    now_ms: Optional[int] = None,
) -> tuple[GoalState, bool]:
    """Add ``delta_tokens`` to ``state.tokens_used`` and check the budget.

    Returns ``(new_state, budget_crossed)`` where ``budget_crossed`` is
    ``True`` exactly when this call was the one that pushed the
    accumulated total past the budget. Callers use the flag to inject
    a one-shot wrap-up prompt rather than a recurring budget-limit
    notice.
    """
    if delta_tokens <= 0:
        return state, False
    if state.status != GoalStatus.ACTIVE:
        # Token accounting is only meaningful for active goals; for
        # paused/terminal/budget_limited we still bump the counter
        # so a later ``resume`` doesn't lose the usage, but we never
        # re-cross the threshold.
        new_total = state.tokens_used + delta_tokens
        now = _now_ms(now_ms)
        return (
            GoalState(
                objective=state.objective,
                status=state.status,
                token_budget=state.token_budget,
                tokens_used=new_total,
                start_time_ms=state.start_time_ms,
                paused_at_ms=state.paused_at_ms,
                accumulated_active_ms=state.accumulated_active_ms,
                blocked_attempts=state.blocked_attempts,
                last_block_reason=state.last_block_reason,
                created_at_ms=state.created_at_ms,
                updated_at_ms=now,
                turns_executed=state.turns_executed,
            ),
            False,
        )
    prev_total = state.tokens_used
    new_total = prev_total + delta_tokens
    budget = state.token_budget
    crossed = budget is not None and prev_total < budget <= new_total
    now = _now_ms(now_ms)
    return (
        GoalState(
            objective=state.objective,
            status=state.status,
            token_budget=state.token_budget,
            tokens_used=new_total,
            start_time_ms=state.start_time_ms,
            paused_at_ms=state.paused_at_ms,
            accumulated_active_ms=state.accumulated_active_ms,
            blocked_attempts=state.blocked_attempts,
            last_block_reason=state.last_block_reason,
            created_at_ms=state.created_at_ms,
            updated_at_ms=now,
            turns_executed=state.turns_executed,
        ),
        crossed,
    )


def mark_budget_limited(state: GoalState, *, now_ms: Optional[int] = None) -> GoalState:
    """Move an active goal into ``budget_limited``.

    Idempotent: a goal already in ``budget_limited`` is returned
    unchanged so the controller can re-fire on every usage event
    without bookkeeping.
    """
    if state.status == GoalStatus.BUDGET_LIMITED:
        return state
    if state.status != GoalStatus.ACTIVE:
        raise GoalStateError(
            f"cannot mark budget_limited from status {state.status.value!r}"
        )
    now = _now_ms(now_ms)
    accumulated = state.accumulated_active_ms + max(
        0, now - state.start_time_ms
    )
    return GoalState(
        objective=state.objective,
        status=GoalStatus.BUDGET_LIMITED,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=None,
        accumulated_active_ms=accumulated,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
    )


def mark_usage_limited(state: GoalState, *, now_ms: Optional[int] = None) -> GoalState:
    """Move an active goal into ``usage_limited`` (rate-limit / offline).

    Like :func:`mark_budget_limited` this is a terminal-until-resume
    state; the user can ``/goal resume`` to flip it back to active.
    """
    if state.status == GoalStatus.USAGE_LIMITED:
        return state
    if state.status != GoalStatus.ACTIVE:
        raise GoalStateError(
            f"cannot mark usage_limited from status {state.status.value!r}"
        )
    now = _now_ms(now_ms)
    accumulated = state.accumulated_active_ms + max(
        0, now - state.start_time_ms
    )
    return GoalState(
        objective=state.objective,
        status=GoalStatus.USAGE_LIMITED,
        token_budget=state.token_budget,
        tokens_used=state.tokens_used,
        start_time_ms=state.start_time_ms,
        paused_at_ms=None,
        accumulated_active_ms=accumulated,
        blocked_attempts=state.blocked_attempts,
        last_block_reason=state.last_block_reason,
        created_at_ms=state.created_at_ms,
        updated_at_ms=now,
        turns_executed=state.turns_executed,
    )


# ---------------------------------------------------------------------------
# Blocked auditing
# ---------------------------------------------------------------------------


def record_blocker(
    state: GoalState, reason: str, *, now_ms: Optional[int] = None
) -> tuple[GoalState, bool]:
    """Record a blocker; return ``(new_state, transitioned_to_blocked)``.

    The counter increments only when ``reason`` matches
    ``state.last_block_reason`` (case-insensitive, trimmed). A
    different reason resets the streak — matching the
    "consecutive 3 times" rule in FEATURE_PLAN.md §2.6.3.3.

    Returns ``(state, False)`` if the streak has not yet hit the
    threshold; ``(blocked_state, True)`` when this call was the one
    that flipped the goal into ``blocked``.
    """
    if state.status != GoalStatus.ACTIVE:
        # Block reports on non-active goals are no-ops: the goal is
        # already terminal or paused and the controller shouldn't
        # silently re-flip it.
        return state, False
    normalized = (reason or "").strip().lower()
    if not normalized:
        raise GoalStateError("blocker reason must be a non-empty string")
    now = _now_ms(now_ms)
    if (
        state.last_block_reason is not None
        and state.last_block_reason.strip().lower() == normalized
    ):
        new_attempts = state.blocked_attempts + 1
    else:
        new_attempts = 1
    transitions = new_attempts >= BLOCKED_CONSECUTIVE_THRESHOLD
    new_status = GoalStatus.BLOCKED if transitions else GoalStatus.ACTIVE
    accumulated = state.accumulated_active_ms
    if transitions:
        accumulated += max(0, now - state.start_time_ms)
    return (
        GoalState(
            objective=state.objective,
            status=new_status,
            token_budget=state.token_budget,
            tokens_used=state.tokens_used,
            start_time_ms=state.start_time_ms,
            paused_at_ms=None,
            accumulated_active_ms=accumulated,
            blocked_attempts=new_attempts if not transitions else 0,
            last_block_reason=None if transitions else normalized,
            created_at_ms=state.created_at_ms,
            updated_at_ms=now,
            turns_executed=state.turns_executed,
        ),
        transitions,
    )


__all__ = [
    "BLOCKED_CONSECUTIVE_THRESHOLD",
    "GoalObjectiveTooLong",
    "GoalStateError",
    "MAX_OBJECTIVE_CHARS",
    "clear_goal",
    "complete_goal",
    "compute_active_elapsed_ms",
    "continue_from_max_turns",
    "mark_budget_limited",
    "mark_usage_limited",
    "pause_goal",
    "record_blocker",
    "resume_goal",
    "set_goal",
    "update_tokens",
]
