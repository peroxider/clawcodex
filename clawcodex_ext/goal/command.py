"""User-facing ``/goal`` slash command.

Implemented as a :class:`clawcodex_ext.command_system.InteractiveCommand`
(the Python analogue of upstream's TS ``local-jsx``) so that:

* ``/goal <objective>`` with an existing non-complete goal can pop
  the spec-mandated replace-confirm dialog via ``ctx.ui.select``.
* ``/goal`` itself (no args) is rejected by
  :func:`is_bridge_safe_command` at the *type* level (the bridge
  gate blocks all ``InteractiveCommand`` instances — see
  ``src/command_system/safe_commands.py:48-53``), matching the
  spec's "`/goal` 命令不是 ``bridgeSafe``" rule.

The command does not own state. It constructs a transient
:class:`GoalController` bound to the current ``session_id`` (read
from ``context.tool_context.session_id`` when available, falling
back to ``context.config['session_id']``) and delegates every
transition to the in-memory registry / persistence layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from clawcodex_ext.command_system.types import (
    InteractiveCommand,
    InteractiveOutcome,
    UIOption,
)

from . import prompts
from .controller import GoalController
from .state_machine import GoalObjectiveTooLong, GoalStateError
from .types import MAX_OBJECTIVE_CHARS, GoalState, GoalStatus

logger = logging.getLogger(__name__)


# Recognised subcommand tokens. Comparison is case-insensitive.
_STATUS = "status"
_CLEAR = "clear"
_PAUSE = "pause"
_RESUME = "resume"
_CONTINUE = "continue"
_COMPLETE = "complete"

# Dialog choices for the replace-confirm prompt (FEATURE_PLAN.md
# §2.6.1: "若已存在非 complete 的目标，必须弹出 GoalReplaceConfirmDialog").
_REPLACE_OPTION = "replace"
_KEEP_OPTION = "keep"

_REPLACE_OPTIONS = (
    UIOption(
        value=_REPLACE_OPTION,
        label="Replace existing goal",
        description="Discard current progress and start the new objective.",
    ),
    UIOption(
        value=_KEEP_OPTION,
        label="Keep current goal",
        description="Drop the new objective and keep working on the existing one.",
    ),
)


@dataclass(frozen=True)
class GoalCommand(InteractiveCommand):
    """``/goal`` slash command.

    Args grammar::

        /goal                       # show status (alias for /goal status)
        /goal status                # show status
        /goal <objective>           # set new objective
        /goal clear                 # clear + tombstone
        /goal pause                 # pause auto-continuation
        /goal resume                # resume from paused / max_turns
        /goal continue              # reset turns counter after max_turns
        /goal complete              # mark complete
    """

    async def run(self, args: str, context: Any) -> InteractiveOutcome:
        controller = self._make_controller(context)
        session_id = controller.session_id
        if not session_id:
            return InteractiveOutcome(
                message=(
                    "No active session — /goal requires a session. "
                    "Start the REPL or resume an existing session first."
                ),
                display="system",
            )

        subcommand, rest = _parse_subcommand(args)
        # ``/goal   `` (whitespace-only, non-empty args) is treated as
        # a usage hint rather than the implicit "show status" branch.
        # The two paths are indistinguishable after ``_parse_subcommand``
        # strips, so we look at the *raw* args here: empty string
        # means the user typed ``/goal`` (status), non-empty-but-blank
        # means they typed garbage.
        if subcommand is None and args and not args.strip():
            return InteractiveOutcome(
                message=(
                    "Usage: `/goal <objective>` (or `/goal status`/`/goal clear`/etc)."
                ),
                display="system",
            )
        try:
            if subcommand is None or subcommand == _STATUS:
                return self._show_status(controller)
            if subcommand == _CLEAR:
                return self._do_clear(controller)
            if subcommand == _PAUSE:
                return self._do_pause(controller)
            if subcommand == _RESUME:
                return self._do_resume(controller)
            if subcommand == _CONTINUE:
                return self._do_continue(controller)
            if subcommand == _COMPLETE:
                return self._do_complete(controller)
            # Anything else is treated as the literal objective text.
            return await self._set_objective(
                controller,
                subcommand + (" " + rest if rest else ""),
                context,
            )
        except GoalObjectiveTooLong as exc:
            return InteractiveOutcome(
                message=(
                    f"Objective is {exc.length} characters; the cap is "
                    f"{exc.max_length}. Write the detail to a file and reference it "
                    "with a short summary, then re-run `/goal <short summary>`."
                ),
                display="system",
            )
        except GoalStateError as exc:
            return InteractiveOutcome(message=str(exc), display="system")

    # ---- helpers ----

    @staticmethod
    def _make_controller(context: Any) -> GoalController:
        """Construct a controller bound to the current session.

        Resolution order:

        1. ``context.tool_context.session_id`` (REPL/TUI surfaces)
        2. ``context.config['session_id']`` (SDK callers)
        3. ``None`` — the resulting controller is read-only.
        """
        session_id: Optional[str] = None
        tool_ctx = getattr(context, "tool_context", None)
        if tool_ctx is not None:
            session_id = getattr(tool_ctx, "session_id", None)
        if session_id is None:
            config = getattr(context, "config", None) or {}
            session_id = config.get("session_id") if isinstance(config, dict) else None
        ctrl = GoalController(session_id=session_id)
        if session_id:
            ctrl.bind(session_id)
        return ctrl

    @staticmethod
    def _show_status(controller: GoalController) -> InteractiveOutcome:
        state = controller.get_state()
        body = prompts.format_status_for_display(state)
        title = "Current goal status" if state is not None else "No active goal"
        # ``ctx.ui.display`` is read-only — it never raises.
        try:
            ctx_ui = _get_ui(controller)
        except Exception:
            ctx_ui = None
        if ctx_ui is not None:
            # Fire-and-forget; the title and body are surfaced for the
            # user-visible status pane.
            try:
                import asyncio

                asyncio.create_task(ctx_ui.display(title, body))
            except Exception:
                pass
        # Also return the body as the outcome message so headless
        # callers (non-interactive surfaces) still get the text.
        return InteractiveOutcome(message=body, display="system")

    @staticmethod
    def _do_clear(controller: GoalController) -> InteractiveOutcome:
        previous = controller.get_state()
        controller.clear()
        return InteractiveOutcome(
            message=(
                "Goal cleared." if previous is not None
                else "No goal was set; nothing to clear."
            ),
            display="system",
        )

    @staticmethod
    def _do_pause(controller: GoalController) -> InteractiveOutcome:
        if controller.get_state() is None:
            return InteractiveOutcome(
                message="No goal to pause.", display="system"
            )
        controller.pause()
        return InteractiveOutcome(
            message="Goal paused. Use `/goal resume` to continue.",
            display="system",
        )

    @staticmethod
    def _do_resume(controller: GoalController) -> InteractiveOutcome:
        state = controller.get_state()
        if state is None:
            return InteractiveOutcome(
                message="No goal to resume.", display="system"
            )
        if state.status not in (GoalStatus.PAUSED, GoalStatus.MAX_TURNS):
            return InteractiveOutcome(
                message=f"Goal is in status {state.status.value!r}; nothing to resume.",
                display="system",
            )
        controller.resume()
        return InteractiveOutcome(
            message="Goal resumed.",
            display="system",
            should_query=True,
        )

    @staticmethod
    def _do_continue(controller: GoalController) -> InteractiveOutcome:
        state = controller.get_state()
        if state is None:
            return InteractiveOutcome(
                message="No goal to continue.", display="system"
            )
        if state.status != GoalStatus.MAX_TURNS:
            return InteractiveOutcome(
                message=(
                    f"Goal is in status {state.status.value!r}; "
                    "/goal continue only applies after max-turns."
                ),
                display="system",
            )
        controller.continue_from_max_turns()
        return InteractiveOutcome(
            message="Goal counter reset; auto-continuation resumed.",
            display="system",
            should_query=True,
        )

    @staticmethod
    def _do_complete(controller: GoalController) -> InteractiveOutcome:
        if controller.get_state() is None:
            return InteractiveOutcome(
                message="No goal to complete.", display="system"
            )
        controller.complete()
        return InteractiveOutcome(
            message="Goal marked complete.",
            display="system",
        )

    @staticmethod
    async def _set_objective(
        controller: GoalController,
        objective: str,
        context: Any = None,
    ) -> InteractiveOutcome:
        text = objective.strip()
        if not text:
            return InteractiveOutcome(
                message=(
                    "Usage: `/goal <objective>` (or `/goal status`/`/goal clear`/etc)."
                ),
                display="system",
            )
        if len(text) > MAX_OBJECTIVE_CHARS:
            raise GoalObjectiveTooLong(len(text), MAX_OBJECTIVE_CHARS)
        existing = controller.get_state()
        # If a non-complete goal is in flight, ask before clobbering it
        # (FEATURE_PLAN.md §2.6.1). COMPLETE goals are *replaced freely*
        # so the user can chain a new objective onto a finished run
        # without first clearing.
        if existing is not None and not existing.is_terminal() or (
            existing is not None and existing.status == GoalStatus.MAX_TURNS
        ):
            # MAX_TURNS is not strictly terminal but represents "we
            # paused because the cap ran out" — still confirm.
            decision = await _confirm_replace(controller, context)
            if decision is None:
                return InteractiveOutcome.skip()
            if decision == _KEEP_OPTION:
                return InteractiveOutcome(
                    message="Keeping the existing goal.", display="system"
                )
        controller.set_new_goal(text)
        return InteractiveOutcome(
            message=(
                f"Goal set: {text[:80]}{'…' if len(text) > 80 else ''}\n"
                "Auto-continuation engaged; the model will keep working "
                "until the goal is complete, paused, or the budget runs out."
            ),
            display="system",
            should_query=True,
        )


async def _confirm_replace(
    controller: GoalController, context: Any = None
) -> Optional[str]:
    """Pop the replace-confirm dialog. Returns the chosen value or
    ``None`` on cancel.

    The active ``UIHost`` is resolved from the supplied ``context``
    first (``context.ui``), then the engine-bridge global fallback
    (``engine._CURRENT_UI``). Headless callers with no UI get
    ``_REPLACE_OPTION`` so the explicit user input is honored.
    """
    ctx_ui = _resolve_ui(context)
    if ctx_ui is None:
        # Headless surface — fall back to "replace" (the user typed
        # the new objective explicitly).
        return _REPLACE_OPTION
    existing = controller.get_state()
    if existing is None:
        return _REPLACE_OPTION
    preview = (
        f"Current objective: {existing.objective[:120]}"
        f"{'…' if len(existing.objective) > 120 else ''}\n"
        f"Status: {existing.status.value}"
    )
    try:
        await ctx_ui.display("Replace existing goal?", preview)
        picked = await ctx_ui.select(
            "An active goal already exists. Replace it?",
            _REPLACE_OPTIONS,
            current=_KEEP_OPTION,
        )
    except Exception:
        logger.exception("replace-confirm dialog failed; defaulting to replace")
        return _REPLACE_OPTION
    return picked


def _resolve_ui(context: Any = None):  # pragma: no cover — trivial
    """Return the active ``UIHost`` for the current invocation.

    Resolution order: ``context.ui`` (the per-call surface passed by
    the command engine) → ``engine._CURRENT_UI`` (the legacy
    bridge-global set by the REPL installer). Returns ``None`` when
    neither is registered so headless callers get a deterministic
    "replace" default.
    """
    if context is not None:
        ui = getattr(context, "ui", None)
        if ui is not None:
            return ui
    try:
        from clawcodex_ext.command_system import engine as engine_mod
        ui = getattr(engine_mod, "_CURRENT_UI", None)
        if ui is not None:
            return ui
    except Exception:
        pass
    return None


def _parse_subcommand(args: str) -> tuple[Optional[str], str]:
    """Split ``args`` into ``(head, rest)``.

    The ``head`` is the first whitespace-delimited token, lower-cased.
    ``rest`` is the remainder with surrounding whitespace stripped.
    """
    text = (args or "").strip()
    if not text:
        return None, ""
    head, _, rest = text.partition(" ")
    return head.lower(), rest.strip()


# The exported command instance wired into ``get_builtin_commands``.
GOAL_COMMAND = GoalCommand(
    name="goal",
    description=(
        "Set, view, or control a long-running goal that the system will "
        "auto-continue working on until completion, pause, or budget limit."
    ),
    argument_hint=(
        "[status | clear | pause | resume | continue | complete | <objective>]"
    ),
    aliases=["g"],  # convenience; matches common REPL convention
    is_enabled=lambda: True,
)


__all__ = ["GOAL_COMMAND", "GoalCommand"]
