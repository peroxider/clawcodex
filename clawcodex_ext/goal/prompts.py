"""XML-wrapped steering prompts for the ``/goal`` system.

FEATURE_PLAN.md §2.6.5 defines a small vocabulary of tags the
controller and the ``/goal`` command inject into the conversation:

* ``<goal-steering type="continuation">`` — every auto-continuation
  round.
* ``<goal-steering type="budget_limit">`` — fired once when the
  token budget is exhausted.
* ``<goal-steering type="objective_updated">`` — fired when the user
  replaces the objective via ``/goal <new>``.
* ``<active-goal ...>...</active-goal>`` — compact context block
  included in the system prompt whenever a goal is active.
* ``<goal-objective-updated>...</goal-objective-updated>`` — meta
  message broadcast alongside the steering prompt when the
  objective changes (matches upstream's
  ``<goal-objective-updated>${trimmed}</goal-objective-updated>``
  shape).

XML wrapping is a deliberate model-side affordance: the tag
boundaries make it trivial for the model to recognise injected
guidance without colliding with normal text.
"""

from __future__ import annotations

from typing import Optional

from .types import GoalState, GoalStatus


# ---------------------------------------------------------------------------
# Steering prompts
# ---------------------------------------------------------------------------


def continuation_prompt(objective: str) -> str:
    """Inject a continuation nudge after each idle round.

    The model is told to keep working on the objective, NOT to ask
    the user a clarifying question unless truly blocked. The
    spec's completion-audit instruction is folded in so the model
    doesn't mark itself done prematurely.
    """
    text = (objective or "").strip()
    return (
        '<goal-steering type="continuation">\n'
        "The active goal is still in progress. Continue working on "
        f"the objective below:\n\n{text}\n\n"
        "Do not stop to ask the user a clarifying question unless "
        "you are truly blocked. When you believe the objective is "
        "satisfied, perform the Completion Audit (objective "
        "decomposition → authoritative evidence per requirement → "
        "no gaps) before reporting completion via the `goal` tool.\n"
        "</goal-steering>"
    )


def budget_limit_prompt(objective: str) -> str:
    """Inject a one-shot wrap-up request when the token budget runs out.

    The model is asked to STOP substantive work, give a progress
    summary, and call ``goal`` with status ``complete`` or
    ``blocked``. This is a one-shot — re-firing would be confusing
    noise.
    """
    text = (objective or "").strip()
    return (
        '<goal-steering type="budget_limit">\n'
        "The token budget for this goal has been exhausted. Stop "
        "any further substantive work. Write a concise progress "
        "summary covering what is complete and what remains for "
        f"the objective below, then call the `goal` tool with "
        "action `update` to mark the goal as `complete` or "
        "`blocked` (with a reason) so a future session can resume.\n\n"
        f"Objective:\n{text}\n"
        "</goal-steering>"
    )


def objective_updated_prompt(new_objective: str) -> str:
    """Inform the model the user replaced the objective mid-flight."""
    text = (new_objective or "").strip()
    return (
        '<goal-steering type="objective_updated">\n'
        "The active goal's objective has been replaced by the "
        "user. Treat this as a hard reset of scope:\n\n"
        f"{text}\n\n"
        "Discard any in-progress assumptions tied to the prior "
        "objective and re-plan from scratch.\n"
        "</goal-steering>"
    )


# ---------------------------------------------------------------------------
# Active-goal context block
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def active_goal_context_block(state: GoalState, *, max_objective_chars: int = 240) -> str:
    """Compact summary shown in the system prompt while a goal is active.

    Per FEATURE_PLAN.md §2.6.8, the pill and context block share the
    same data but the context block keeps a richer view of state
    transitions (status, elapsed, turns, budget) so the model can
    reason about its current progress without re-deriving it from
    the conversation history.
    """
    objective = _truncate(state.objective, max_objective_chars)
    budget = (
        f"{state.tokens_used}/{state.token_budget}"
        if state.token_budget is not None
        else f"{state.tokens_used}/∞"
    )
    return (
        f'<active-goal status="{state.status.value}" '
        f'turns="{state.turns_executed}" tokens="{budget}">'
        f"{objective}"
        "</active-goal>"
    )


# ---------------------------------------------------------------------------
# Meta-message companion for objective updates
# ---------------------------------------------------------------------------


def objective_updated_meta_message(new_objective: str) -> str:
    """Meta message broadcast alongside the steering prompt on update.

    Matches the upstream shape
    ``<goal-objective-updated>${trimmed}</goal-objective-updated>``
    so persisted transcripts are byte-compatible with the reference
    implementation.
    """
    text = (new_objective or "").strip()
    return f"<goal-objective-updated>\n{text}\n</goal-objective-updated>"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def format_status_for_display(
    state: Optional[GoalState], *, now_ms: Optional[int] = None
) -> str:
    """Human-readable status block used by the ``/goal status`` command.

    Kept here (not in the command module) because the same format
    drives both the slash command and the REPL/TUI pill, and tests
    should not have to mount a full UIHost to assert text.
    """
    if state is None:
        return "No active goal. Use `/goal <objective>` to set one."
    elapsed_ms = _elapsed_ms(state, now_ms)
    minutes, seconds = divmod(elapsed_ms // 1000, 60)
    budget_str = (
        f"{state.tokens_used}/{state.token_budget}"
        if state.token_budget is not None
        else f"{state.tokens_used}/∞"
    )
    lines = [
        f"Status: {state.status.value}",
        f"Objective: {state.objective}",
        f"Elapsed: {minutes}m {seconds}s",
        f"Tokens: {budget_str}",
        f"Turns executed: {state.turns_executed}",
    ]
    if state.blocked_attempts:
        lines.append(f"Blocked streak: {state.blocked_attempts}")
    return "\n".join(lines)


def format_pill(state: Optional[GoalState], *, objective_max_chars: int = 30) -> str:
    """Compact one-line pill for status bars.

    Returns ``""`` when no goal is set so the caller can splice it
    into an existing line without a conditional.
    """
    if state is None:
        return ""
    obj = _truncate(state.objective, objective_max_chars)
    if state.token_budget is not None:
        budget_str = f"{_compact_number(state.tokens_used)}/{_compact_number(state.token_budget)}"
    else:
        budget_str = f"{_compact_number(state.tokens_used)}"
    return f"[{state.status.value.title()} · {obj} · {budget_str}]"


def _compact_number(value: int) -> str:
    """Render large token counts in a UI-friendly shorthand."""
    v = max(0, int(value))
    if v < 1000:
        return str(v)
    if v < 10_000:
        return f"{v / 1000:.1f}k"
    if v < 1_000_000:
        return f"{v // 1000}k"
    return f"{v / 1_000_000:.1f}M"


def _elapsed_ms(state: GoalState, now_ms: Optional[int]) -> int:
    if state.status == GoalStatus.ACTIVE and state.start_time_ms > 0:
        if now_ms is None:
            import time as _time

            now_ms = int(_time.time() * 1000)
        return state.accumulated_active_ms + max(0, int(now_ms) - state.start_time_ms)
    return state.accumulated_active_ms


__all__ = [
    "active_goal_context_block",
    "budget_limit_prompt",
    "continuation_prompt",
    "format_pill",
    "format_status_for_display",
    "objective_updated_meta_message",
    "objective_updated_prompt",
]
