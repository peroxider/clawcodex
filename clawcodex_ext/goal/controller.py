"""Glue between the REPL turn loop, the goal registry, and persistence.

``GoalController`` is the lifecycle hook owner. It does not own
state — every read/write goes through
:func:`clawcodex_ext.goal.registry.get_goal_registry` so the
in-memory cache stays consistent across the slash command, the
model-side tool, the REPL turn loop, and the UI pill.

Lifecycle (driven by ``clawcodex_ext/repl/app.py`` paralleling the
existing ``AwaySummaryController`` wiring):

* ``on_run_start()`` — fired before the user's ``chat()`` call.
  Resets the aborted flag; the goal is allowed to extend across
  turns until a continuation actually completes.
* ``on_run_finish()`` — fired after ``chat()`` returns normally.
  No-op for state but a convenient place for instrumentation.
* ``on_assistant_turn_complete()`` — fired after the assistant turn
  ends. Decides whether to inject a continuation prompt (active
  goal, ``turns_executed < MAX_GOAL_TURNS``, not aborted, not in
  plan mode, not usage-limited). When a continuation is queued the
  caller is expected to feed it back into ``chat()`` for another
  round.

Token accounting is driven from
``src/query/agent_loop_compat.py``: every model response's usage
dict is fed into :meth:`record_usage`, which calls
``update_tokens`` on the in-memory state. When the budget is
crossed the controller queues a one-shot
:func:`budget_limit_prompt <clawcodex_ext.goal.prompts.budget_limit_prompt>`
instead of a continuation.

Persistence is best-effort: every state mutation calls
:meth:`persist` which delegates to
:func:`clawcodex_ext.goal.storage.persist_goal`. Failures are
logged and swallowed so a transient disk error cannot break
auto-continuation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from . import prompts
from .registry import get_goal_registry
from .state_machine import (
    GoalObjectiveTooLong,
    GoalStateError,
    clear_goal,
    complete_goal,
    continue_from_max_turns,
    increment_turns,
    mark_budget_limited,
    mark_usage_limited,
    pause_goal,
    record_blocker,
    resume_goal,
    set_goal,
    update_tokens,
)
from .storage import persist_goal, persist_goal_cleared
from .types import (
    MAX_GOAL_TURNS,
    MAX_OBJECTIVE_CHARS,
    GoalState,
    GoalStatus,
)

logger = logging.getLogger(__name__)


class GoalController:
    """REPL-facing controller for a single ``session_id``."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        *,
        session_id_getter: Optional[Callable[[], Optional[str]]] = None,
        display: Optional[Callable[[str], None]] = None,
    ) -> None:
        # ``session_id`` is the legacy synchronous binding — used by the
        # transient controller built inside the ``/goal`` command and
        # the ``Goal`` tool, where the session id is already known.
        # ``session_id_getter`` is the lazy variant used by the
        # REPL/TUI installer so the controller follows session swaps
        # (``/provider``, ``/resume``) without being re-installed.
        self._session_id_getter = session_id_getter
        self._display = display
        self._session_id = session_id or (
            session_id_getter() if session_id_getter is not None else None
        )
        self._was_aborted = False
        self._plan_mode = False
        # Pending outputs the REPL drains each turn. ``pending_injection``
        # is a single ``{text, is_meta}`` dict (one continuation or wrap-up
        # at a time); ``pending_meta_messages`` are zero-or-more
        # broadcast notifications (e.g. ``<goal-objective-updated>``).
        self._pending_injection: Optional[dict[str, Any]] = None
        self._pending_meta_messages: list[str] = []
        # ``_budget_already_injected`` ensures the wrap-up prompt is
        # a one-shot even if usage keeps flowing in after the crossing.
        self._budget_already_injected = False

    # ---- session binding ----

    def bind(self, session_id: str) -> None:
        """Bind to a ``session_id``. Subsequent lifecycle calls operate on
        this session's :class:`GoalState`."""
        self._session_id = session_id
        self._budget_already_injected = False
        self._was_aborted = False
        self._pending_injection = None
        self._pending_meta_messages = []

    def _refresh_session_id(self) -> Optional[str]:
        """Refresh the bound ``session_id`` from the lazy getter, if any.

        Called at the start of every operation so a session swap
        (``/provider``, ``/resume``) is picked up without re-
        installing the controller. The result is also returned for
        convenience.
        """
        if self._session_id_getter is not None:
            try:
                self._session_id = self._session_id_getter()
            except Exception:
                logger.exception("session_id_getter failed; keeping prior id")
        return self._session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # ---- environment signals ----

    def mark_aborted(self) -> None:
        """Indicate the most recent turn was interrupted (Ctrl+C / Ctrl+B).

        The next :meth:`on_assistant_turn_complete` will skip
        continuation injection and reset the flag so the turn *after*
        the interrupt can resume normal auto-pumping.
        """
        self._was_aborted = True

    def set_plan_mode(self, enabled: bool) -> None:
        """Suppress continuation injection while plan mode is active."""
        self._plan_mode = bool(enabled)

    # ---- read ----

    def get_state(self) -> Optional[GoalState]:
        """Return the current :class:`GoalState` for the bound session."""
        return get_goal_registry().get(self._session_id)

    def get_pill_state(self) -> Optional[dict[str, Any]]:
        """Return a UI-friendly dict for the status-bar pill.

        Returns ``None`` when no goal is active so the UI layer can
        render a clean "no goal" segment.
        """
        state = self.get_state()
        if state is None:
            return None
        return {
            "status": state.status.value,
            "objective": state.objective,
            "tokens_used": state.tokens_used,
            "token_budget": state.token_budget,
            "turns_executed": state.turns_executed,
            "pill": prompts.format_pill(state),
        }

    def drain_pending_injection(self) -> Optional[dict[str, Any]]:
        """Pop and return the next pending continuation/budget-limit prompt.

        Returns ``None`` when no injection is queued. The REPL is
        expected to call this once per turn-completion cycle and
        feed ``text`` back into ``chat()`` when ``is_meta`` is
        ``False``.
        """
        out = self._pending_injection
        self._pending_injection = None
        return out

    def drain_pending_meta_messages(self) -> list[str]:
        """Pop and return any pending meta messages broadcast this turn."""
        out = list(self._pending_meta_messages)
        self._pending_meta_messages.clear()
        return out

    # ---- write entry points (used by command.py) ----

    def set_new_goal(
        self,
        objective: str,
        *,
        token_budget: Optional[int] = None,
    ) -> GoalState:
        """Replace the current goal with a fresh active one.

        Raises :class:`GoalObjectiveTooLong` for over-long input.
        Persists the new state to the transcript and queues an
        ``<goal-objective-updated>`` meta message so the model
        sees the change on its next turn.
        """
        previous = self.get_state()
        new_state = set_goal(
            previous,
            objective,
            token_budget=token_budget,
        )
        get_goal_registry().set(self._session_id, new_state)
        persist_goal(self._session_id, new_state)
        self._budget_already_injected = False
        # Always broadcast the update — the model needs to know.
        self._pending_meta_messages.append(
            prompts.objective_updated_meta_message(new_state.objective)
        )
        # Also queue a steering prompt so the model's *next* output is
        # forced to acknowledge the new scope. The REPL drains this via
        # ``drain_pending_injection`` once per turn.
        self._pending_injection = {
            "text": prompts.objective_updated_prompt(new_state.objective),
            "is_meta": True,
            "kind": "objective_updated",
        }
        return new_state

    def pause(self) -> GoalState:
        new_state = self._apply(pause_goal)
        persist_goal(self._session_id, new_state)
        return new_state

    def resume(self) -> GoalState:
        # ``resume`` resets the blocked streak per spec — the
        # state machine's ``resume_goal`` already does this; we just
        # make sure the budget-injected latch is re-armed so a future
        # budget crossing re-fires the wrap-up.
        new_state = self._apply(resume_goal)
        persist_goal(self._session_id, new_state)
        self._budget_already_injected = False
        return new_state

    def complete(self) -> GoalState:
        new_state = self._apply(complete_goal)
        persist_goal(self._session_id, new_state)
        return new_state

    def continue_from_max_turns(self) -> GoalState:
        new_state = self._apply(continue_from_max_turns)
        persist_goal(self._session_id, new_state)
        return new_state

    def mark_usage_limited(self) -> GoalState:
        """Flag the goal as rate-limited / offline.

        Called by the agent loop when the provider returns 429 or a
        network error. The user can ``/goal resume`` to recover.
        """
        new_state = self._apply(mark_usage_limited)
        persist_goal(self._session_id, new_state)
        return new_state

    def clear(self) -> None:
        """Drop the goal and write a tombstone to the transcript."""
        if not self._session_id:
            return
        get_goal_registry().clear(self._session_id)
        persist_goal_cleared(self._session_id)
        # Broadcast a "cleared" meta message so the model knows not
        # to keep producing work tied to the old objective.
        self._pending_meta_messages.append(
            prompts.objective_updated_meta_message("cleared")
        )
        self._budget_already_injected = False

    def record_blocker(self, reason: str) -> tuple[GoalState, bool]:
        """Record a blocker reason from the model. Returns
        ``(state, transitioned_to_blocked)``."""
        return self._apply2(record_blocker, reason)

    # ---- lifecycle hooks ----

    def on_run_start(self) -> None:
        """Reset the per-run aborted flag."""
        self._was_aborted = False

    def on_run_finish(self) -> None:
        """No-op for state; kept for symmetry / future instrumentation."""
        return

    def on_assistant_turn_complete(self) -> Optional[dict[str, Any]]:
        """Fire after the assistant's turn ends. Returns the queued
        injection for the REPL to feed back into ``chat()``.

        Decisions:

        * No active goal → no-op.
        * ``paused`` / terminal → no-op.
        * ``aborted`` → no-op (and the flag is cleared).
        * ``plan_mode`` → no-op.
        * ``turns_executed >= MAX_GOAL_TURNS`` → flip to ``MAX_TURNS``,
          persist, no injection.
        * otherwise → increment turns, queue a continuation prompt.
        """
        if not self._refresh_session_id():
            return None
        state = self.get_state()
        if state is None or state.status != GoalStatus.ACTIVE:
            return None
        if self._was_aborted:
            # Honor the spec: don't auto-continuation after an abort.
            self._was_aborted = False
            return None
        if self._plan_mode:
            return None

        # Increment turns first; this may flip the state to MAX_TURNS.
        try:
            new_state, hit_max = self._apply2(increment_turns)
        except GoalStateError:
            return None
        if hit_max:
            logger.info(
                "goal %s reached MAX_GOAL_TURNS=%d",
                self._session_id, MAX_GOAL_TURNS,
            )
            return None

        # Active after increment_turns → queue continuation.
        self._pending_injection = {
            "text": prompts.continuation_prompt(new_state.objective),
            "is_meta": True,
            "kind": "continuation",
        }
        return self._pending_injection

    # ---- token usage hook ----

    def record_usage(self, usage: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Hook called by ``src/query/agent_loop_compat.py`` after each model
        response.

        Returns the queued injection (one-shot wrap-up) when the
        budget was crossed on this call, else ``None``. The REPL
        should drain pending injections after each turn.
        """
        if not self._refresh_session_id():
            return None
        if not isinstance(usage, dict):
            return None
        delta = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("output_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
        )
        if delta <= 0:
            return None
        try:
            new_state, crossed = self._apply2(update_tokens, delta)
        except GoalStateError:
            return None
        if crossed and not self._budget_already_injected:
            self._budget_already_injected = True
            # Flip the state to budget_limited so subsequent
            # continuation injections are suppressed until resume.
            try:
                limited = self._apply(mark_budget_limited)
            except GoalStateError:
                limited = new_state
            self._pending_injection = {
                "text": prompts.budget_limit_prompt(limited.objective),
                "is_meta": True,
                "kind": "budget_limit",
            }
            return self._pending_injection
        return None

    # ---- internals ----

    def _apply(self, fn, *args, **kwargs):
        """Run a 0-arg transition ``fn`` on the current state via the registry."""
        if not self._session_id:
            raise GoalStateError("controller is not bound to a session_id")
        return get_goal_registry().update(
            self._session_id,
            lambda current: fn(current, *args, **kwargs)
            if current is not None
            else None,
        )

    def _apply2(self, fn, *args, **kwargs):
        """Same as :meth:`_apply` but returns the full transition result
        tuple (state, flag) instead of just the new state."""
        if not self._session_id:
            raise GoalStateError("controller is not bound to a session_id")
        captured: list = []

        def runner(current: Optional[GoalState]):
            if current is None:
                raise GoalStateError("transition requires an existing goal")
            result = fn(current, *args, **kwargs)
            captured.append(result)
            # ``result`` may be a tuple; we always want the new state.
            return result[0] if isinstance(result, tuple) else result

        get_goal_registry().update(self._session_id, runner)
        if not captured:
            raise GoalStateError("transition did not produce a result")
        return captured[0]


__all__ = ["GoalController"]
