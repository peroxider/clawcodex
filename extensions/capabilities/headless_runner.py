"""Headless runner registry.

Provides a pluggable headless execution backend. By default, delegates to
``src.entrypoints.headless.run_headless`` (upstream). Callers in
``src.api.query`` use only the ``run_headless_session`` function below,
which keeps the runtime import off the upstream path.

Usage::

    from src.capabilities.headless_runner import run_headless_session

    exit_code = run_headless_session(
        prompt="...",
        workspace_root=Path("."),
        on_event=lambda event: ...,
    )
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = ["HeadlessSessionOptions", "run_headless_session"]

# Environment flag to override the headless runner backend
_HEADLESS_RUNNER_BACKEND = os.getenv("CLAW_HEADLESS_BACKEND", "").lower()


@dataclass
class HeadlessSessionOptions:
    """Options for a headless session run.

    Mirrors the fields of ``src.entrypoints.headless.HeadlessOptions``
    that ``src.api.query.QueryRunner`` actually uses.
    """

    prompt: str
    workspace_root: Path
    provider_name: str | None = None
    model: str | None = None
    max_turns: int = 20
    permission_mode: str = "dontAsk"
    stdout: io.StringIO = field(default_factory=io.StringIO)
    stderr: io.StringIO = field(default_factory=io.StringIO)
    on_event: Callable[[Any], None] = field(default=lambda e: None)
    # Environment variables merged into the headless session's
    # subprocess env. Values override inherited daemon env.
    env: dict[str, str] = field(default_factory=dict)
    # Prompt split: text appended to the effective system prompt
    # built by ``run_headless``. Carries the constant workflow background
    # (project, conventions, decoupling principles) so the per-turn user
    # message can be just the issue content / continuation.
    append_system_prompt: str | None = None
    # External abort controller forwarded to the headless session so the
    # caller (QueryRunner) can cooperatively cancel a session running on
    # an executor thread it cannot otherwise kill.
    abort_controller: Any | None = None
    # Agent identity for pending_messages drain.
    # When set, the headless session's ToolContext gets this agent_id
    # and runtime_tasks, enabling real-time inject at ToolResult
    # boundaries via _drain_pending_user_messages.
    agent_id: str | None = None
    runtime_tasks: Any | None = None
    # When set, run_headless calls Session.resume()
    # to load the existing transcript into the Conversation.
    resume_session_id: str | None = None


def make_abort_controller() -> Any:
    """Create an AbortController without importing upstream at module load.

    ``QueryRunner`` uses this to obtain a controller it can trip on
    wall-clock timeout / generator teardown; the same instance is
    forwarded into the headless session via
    ``HeadlessSessionOptions.abort_controller``.
    """
    from src.utils.abort_controller import AbortController

    return AbortController()


def run_headless_session(
    options: HeadlessSessionOptions,
) -> int:
    """Run a headless session and return the exit code.

    This function dispatches to the configured backend:

    * Default (``CLAW_HEADLESS_BACKEND=""``): delegates to
      ``src.entrypoints.headless.run_headless``, importing it lazily
      at call time. This preserves the existing behaviour and keeps
      the import off the module-load path.
    * ``CLAW_HEADLESS_BACKEND=upstream``: same as default.
    * ``CLAW_HEADLESS_BACKEND=stub``: returns 0 immediately (useful for
      tests that do not exercise the full agent loop).

    Custom backends can be registered via ``set_headless_backend()``.
    """
    backend = _HEADLESS_RUNNER_BACKEND or _active_backend[0]

    if backend == "stub":
        # Exercise the event bridge to ensure callers still work,
        # but don't actually run the agent.
        options.on_event(_make_stub_tool_event("tool_use", "bash", {}, None, "1"))
        options.on_event(_make_stub_tool_event("tool_result", "bash", {"output": "ok"}, False, "1"))
        return 0

    # Default: lazy import of the real upstream headless runner.
    # Forward the on_event callback so tool events from the headless
    # session reach the orchestrator's event stream (e.g. for tool_count).
    # Import from the downstream implementation facade rather than src/
    # so this capabilities module does not depend on upstream internals.
    from clawcodex_ext.entrypoints.headless import HeadlessOptions, run_headless

    options_legacy = HeadlessOptions(
        prompt=options.prompt,
        output_format="text",
        provider_name=options.provider_name,
        model=options.model,
        max_turns=options.max_turns,
        permission_mode=options.permission_mode,
        workspace_root=options.workspace_root,
        stdout=options.stdout,
        stderr=options.stderr,
        on_event=options.on_event,
        env=options.env,
        append_system_prompt=options.append_system_prompt or "",
        abort_controller=options.abort_controller,
        agent_id=options.agent_id,
        runtime_tasks=options.runtime_tasks,
        resume_session_id=options.resume_session_id,
    )
    from clawcodex_ext.coordinator.mode import coordinator_mode_context

    coordinator_enabled = str(
        options.env.get("CLAUDE_CODE_COORDINATOR_MODE", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    with coordinator_mode_context(coordinator_enabled):
        return run_headless(options_legacy)


# ---------------------------------------------------------------------------
# Stub event factory (used by stub backend)
# ---------------------------------------------------------------------------


def _make_stub_tool_event(
    kind: str,
    tool_name: str,
    tool_input: dict[str, Any],
    is_error: bool,
    tool_use_id: str,
) -> Any:
    """Build a minimal object duck-typing as a ToolEvent."""

    # The on_event callback passed to run_headless receives a ToolEvent
    # (a frozen dataclass). We construct a lightweight object that has
    # the same attribute layout so the event bridge in query.py works.
    class _StubEvent:
        __slots__ = (
            "kind",
            "tool_name",
            "tool_input",
            "tool_output",
            "tool_use_id",
            "is_error",
            "error",
        )

        def __init__(self):
            self.kind = kind
            self.tool_name = tool_name
            self.tool_input = tool_input
            self.tool_output: Any = None
            self.tool_use_id = tool_use_id
            self.is_error = is_error
            self.error: str | None = None

    return _StubEvent()


# ---------------------------------------------------------------------------
# Backend registry (allows tests / custom embeddings to override)
# ---------------------------------------------------------------------------

_active_backend: list[str] = ["upstream"]


def set_headless_backend(name: str) -> None:
    """Set the active headless runner backend.

    Args:
        name: One of "upstream" or "stub".
    """
    _active_backend[0] = name
