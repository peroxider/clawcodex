"""F-43 extension hook for the REPL frontend.

This module owns the downstream side of the F-43 ``/provider`` and
``/model`` slash command wiring for :class:`src.repl.core.ClawcodexREPL`.
The goal is to keep all F-43 knowledge in ``clawcodex_ext/`` so the
upstream-shaped REPL core (``src/repl/core.py``) only sees a thin seam
(``runtime_context`` field + observer notification on swap).

Responsibilities
----------------
1. Register the F-43 ``/provider`` and ``/model`` ``LocalCommand``
   objects on the REPL's command registry.
2. Install a :class:`RuntimeObserver` that syncs the REPL's private
   ``provider`` / ``tool_registry`` / ``tool_context`` references after
   a :meth:`RuntimeContext.swap_provider` rebuild.

The frontend plugin (:class:`clawcodex_ext.frontend.repl.REPLFrontend`)
calls :func:`install_repl_extensions` immediately after
``ClawcodexREPL(...)`` construction but before ``repl.run()``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clawcodex_ext.away_summary.controller import AwaySummaryController
from clawcodex_ext.away_summary.registration import register_away_summary_commands
from clawcodex_ext.cli.runtime_commands import register_runtime_commands
from clawcodex_ext.runtime.observer import RuntimeObserver, attach_observer

if TYPE_CHECKING:  # pragma: no cover
    from src.repl.core import ClawcodexREPL

_log = logging.getLogger(__name__)


class _ReplRuntimeObserver:
    """Sync REPL private state when the runtime swaps provider.

    Implements :class:`RuntimeObserver`. The REPL holds cached
    references to ``provider`` / ``tool_registry`` / ``tool_context`` and
    a command context that mirrors them; all four must be refreshed
    after a provider swap so the next prompt uses the new model.
    """

    def __init__(self, repl: "ClawcodexREPL") -> None:
        self._repl = repl

    def on_runtime_swap(self, runtime) -> None:
        repl = self._repl
        repl.provider = runtime.provider
        repl.provider_name = runtime.provider_name
        repl.tool_registry = runtime.tool_registry
        repl.tool_context = runtime.tool_context
        if hasattr(repl, "command_context") and repl.command_context is not None:
            repl.command_context.provider = runtime.provider
            repl.command_context.tool_registry = runtime.tool_registry
            repl.command_context.tool_context = runtime.tool_context


def install_repl_extensions(repl: "ClawcodexREPL", ctx) -> None:
    """Wire F-43 slash commands + observer into the REPL.

    Args:
        repl: A fully-constructed :class:`ClawcodexREPL`. The function
            reads ``repl.command_registry`` and ``repl.runtime_context``;
            it does not mutate the REPL's public surface beyond
            registering commands and attaching an observer.
        ctx: The downstream :class:`RuntimeContext` (or any object
            exposing the runtime protocol). Used to attach the observer
            that fires on ``swap_provider``.
    """
    # Register /provider and /model into the REPL's local command
    # registry so the slash-command dispatcher can find them.
    if getattr(repl, "command_registry", None) is not None:
        register_runtime_commands(repl.command_registry)
        register_away_summary_commands(repl.command_registry)
        update_commands = getattr(
            repl,
            "_update_built_in_commands_with_command_system",
            None,
        )
        if callable(update_commands):
            update_commands()

    _install_away_summary_controller(repl)
    _install_goal_controller(repl)

    runtime = getattr(repl, "runtime_context", None)
    if runtime is None:
        runtime = ctx
    if runtime is None:
        return

    attach_observer(runtime, _ReplRuntimeObserver(repl))

    # ---- SIGTERM / SIGINT: save session + print resume hint (S-R1) ----
    _register_signal_session_save(repl)


def _install_away_summary_controller(repl: "ClawcodexREPL") -> None:
    if getattr(repl, "_away_summary_controller", None) is not None:
        return

    session = getattr(repl, "session", None)
    conversation = getattr(session, "conversation", None)
    if conversation is None:
        return

    def _display(text: str) -> None:
        print_recap = getattr(repl, "_print_local_command_text", None)
        if callable(print_recap):
            print_recap(text, command="recap")
            return
        console = getattr(repl, "console", None)
        if console is not None:
            console.print(text)

    repl._away_summary_controller = AwaySummaryController(
        conversation=conversation,
        provider_getter=lambda: getattr(repl, "provider", None),
        model_getter=lambda: getattr(getattr(repl, "provider", None), "model", None),
        session_getter=lambda: getattr(repl, "session", None),
        display=_display,
    )


def _install_goal_controller(repl: "ClawcodexREPL") -> None:
    """F-9: wire the ``/goal`` auto-continuation controller onto the REPL.

    The controller is a thin shim over the process-level
    ``GoalStateRegistry`` singleton (see
    ``clawcodex_ext/goal/registry.py``). It exposes
    ``on_run_start`` / ``on_run_finish`` / ``on_assistant_turn_complete``
    that the overridden ``ClawcodexREPL.chat()`` invokes in its
    ``finally`` block, mirroring the upstream
    ``AwaySummaryController`` pattern.

    The controller binds lazily on first call: the REPL's
    ``session.session_id`` is captured at ``chat()`` time rather than
    at install time, so a session swap (``/provider``,
    ``/resume``) does not strand the controller on a stale id.
    """
    if getattr(repl, "_goal_controller", None) is not None:
        return

    def _session_id() -> str | None:
        return getattr(getattr(repl, "session", None), "session_id", None)

    def _display(text: str) -> None:
        console = getattr(repl, "console", None)
        if console is not None:
            try:
                console.print(text)
                return
            except Exception:
                pass
        print_recap = getattr(repl, "_print_local_command_text", None)
        if callable(print_recap):
            try:
                print_recap(text, command="goal")
            except Exception:
                pass

    from clawcodex_ext.goal.controller import GoalController

    repl._goal_controller = GoalController(
        session_id_getter=_session_id,
        display=_display,
    )


def _register_signal_session_save(repl: "ClawcodexREPL") -> None:
    """Register a graceful-shutdown cleanup that saves the session and
    prints a resume hint when the process receives SIGTERM/SIGINT.

    Uses the upstream ``register_cleanup`` from ``src.utils.graceful_shutdown``
    which is already installed by ``init()``.

    The print is delegated to :func:`clawcodex_ext.utils.resume_hint.print_resume_hint`
    so the hint is centralised — and that helper's process-wide latch
    keeps the hint to a single emission even if the inline REPL ``/exit``
    path has already printed one. The ``session.save()`` call is
    unconditional because persistence must run regardless of whether the
    user has already seen the hint.
    """
    try:
        from src.utils.graceful_shutdown import register_cleanup
    except ImportError:
        return

    # Capture session reference once at registration time and again
    # just before the cleanup runs (the REPL may swap sessions mid-run).
    sid_ref = {"session": None}

    def _capture_ref() -> None:
        sid_ref["session"] = getattr(repl, "session", None)

    _capture_ref()

    def _cleanup() -> None:
        _capture_ref()
        session = sid_ref["session"]
        if session is None:
            return
        # Always persist — independent of whether the hint gets printed.
        try:
            session.save()
        except Exception:
            pass
        # Print via the canonical helper. Its process-wide latch
        # suppresses the duplicate if ``/exit`` already printed.
        try:
            from clawcodex_ext.utils.resume_hint import print_resume_hint

            print_resume_hint(getattr(session, "session_id", None))
        except Exception:
            pass

    register_cleanup(_cleanup)
