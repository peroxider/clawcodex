"""REPL launcher shims.

Mirrors the role of ``typescript/src/replLauncher.tsx`` in the Python
port: a thin factory that decides how to boot the interactive REPL.

**Architecture changes in bridge-refactor**: The launcher now properly
decouples bridge initialization from UI selection:

1. **Textual TUI path** (default): ``entrypoints.tui.run_tui()`` creates
   ``ClawCodexTUI`` which owns a ``BridgeManager`` instance. The bridge
   lifecycle is managed by the app, not the launcher.

2. **Legacy REPL path**: ``repl.core.PromptSession`` runs without bridge
   by default (bridge integration comes in a follow-up phase).

The ``launch_repl()`` function serves as the public entry point, similar
to ``launchRepl()`` in the TypeScript reference. It delegates to the
appropriate mode runner based on ``prefer_tui`` and environment.

For bridge-enabled sessions, the ``BridgeManager`` is initialized inside
``ClawCodexTUI.on_mount()`` after the REPL screen is pushed, allowing
the bridge to start polling only when the UI is ready.

Composition diagram (entry-point relationships)::

                        cli.main()
                           |
                   +-------+--------+
                   v                v
      cli._run_tui_mode (--tui)   cli.start_repl (default)
                   |                |
                   v                v
       entrypoints.tui.run_tui   repl.core.PromptSession
       entrypoints.tui.run_tui        |
                   |                ^ (slash command /tui handoff)
                   v                |
            tui.app.ClawCodexTUI ---+
                   |
                   +---> BridgeManager (on_mount, after screen push)

The handoff arrow is one-way: ``/tui`` from inside the legacy REPL boots
the Textual UI and returns to the shell when the user exits the TUI; the
legacy REPL does not auto-resume after the round trip (state carry-over
is read-only via ``_replay_history_to_host``). See
``my-docs/ch13-terminal-ui-refactoring-plan.md`` working assumption A12.
"""

from __future__ import annotations

import sys
from pathlib import Path


def build_repl_banner() -> str:
    """One-line banner used by tests to confirm the module loads."""

    return (
        "ClawCodex REPL (Textual TUI with BridgeManager integration; "
        "legacy Rich REPL opt-in via --legacy-repl or /legacy)."
    )


def launch_repl(
    *,
    prefer_tui: bool | None = None,
    workspace_root: Path | None = None,
    stream: bool = True,
    resume_session_id: str | None = None,
    resume_browse: bool = False,
) -> int:
    """Boot the interactive UI.

    Args:
        prefer_tui: ``True`` forces the Textual TUI, ``False`` forces the
            legacy Rich REPL, ``None`` auto-detects via
            :func:`src.entrypoints.tui.should_use_tui`.
        workspace_root: Override the workspace root for the Textual path.
        stream: Whether the legacy REPL should enable live streaming.
        resume_session_id: Session ID to resume (None for fresh session).
        resume_browse: If True and resume_session_id is None, show session picker.

    Returns:
        A conventional process exit code.
    """
    # Import here to avoid circular imports and to allow early exit
    # for the fast-path subcommands (--version, --config, etc.)
    from src.entrypoints.tui import should_use_tui

    if should_use_tui(prefer_tui):
        from src.entrypoints.tui import TUIOptions, run_tui

        return run_tui(TUIOptions(
            workspace_root=workspace_root,
            stream=stream,
            resume_session_id=resume_session_id,
            resume_browse=resume_browse,
        ))

    # Legacy REPL path - no bridge integration in initial phase
    from src.cli import start_repl

    return start_repl(stream=stream, resume_session_id=resume_session_id)


def print_resume_hint(session_id: str, title: str | None = None) -> None:
    """Print the resume hint after exit, matching the TS reference behavior.

    This mirrors ``gracefulShutdown.ts::printResumeHint()`` - prints the
    hint synchronously before any async cleanup to ensure visibility
    even if the process is killed.
    """
    import os

    if not os.isatty(sys.stdout.fileno()):
        return

    if title:
        # Escape the title for shell safety
        escaped = title.replace('\\', '\\\\').replace('"', '\\"')
        print(f"\n\033[2mResume this session with:\nclawcodex --resume \"{escaped}\"\033[0m")
    else:
        print(f"\n\033[2mResume this session with:\nclawcodex --resume {session_id}\033[0m")


def capture_exit_transcript(repl_screen) -> list[Any]:
    """Capture the transcript renderables at exit time.

    Mirrors the TS ``exit_snapshot`` pattern where the conversation
    the user saw stays on-screen after /exit.
    """
    if repl_screen is None:
        return []
    try:
        return list(repl_screen.transcript.snapshot())
    except Exception:
        return []
