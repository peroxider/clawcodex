"""Public Python API for running a single query.

Wraps the headless entrypoint for programmatic use.
"""

from __future__ import annotations

import asyncio
import io
import queue
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from .debug_log import append_debug_event

if TYPE_CHECKING:
    from ..capabilities.event_protocol import ToolEventProtocol
    from ..capabilities.headless_runner import HeadlessSessionOptions


# F-108 P108-B — wall-clock budget for a single headless query run.
# The runner spawns ``run_headless_session`` on the default executor and
# awaits the resulting future; without a bound that future can hang
# forever (see F-108 §十八 risk #5). ``asyncio.wait_for`` below cuts the
# wait at ``_QUERY_TIMEOUT_S`` seconds, yielding
# ``SessionComplete(reason="exit_code=124")`` so callers can detect the
# timeout via the conventional GNU exit code.
#
# ``asyncio.wait_for`` does NOT cancel an executor future — Python's
# executor futures cannot be killed from the event loop — so the
# underlying thread may keep running until ``run_headless_session``
# returns naturally. The headless session is expected to honour
# ``AbortController`` for cooperative cancellation in F-108 P108-G;
# until then this is a known limitation called out in F-108 §十八 risk
# table.
#
# Set to ``0`` to disable the timeout (F-108 §十八 design decision #5:
# every Layer-2 budget has a ``0`` escape hatch).
#
# TODO(F-108 P108-E): plumb this through ``AgentConfig.freeze.agent_loop_timeout_s``
# so the value is configurable per-run instead of being hard-coded.
_QUERY_TIMEOUT_S = 300.0


@dataclass
class QueryConfig:
    """Configuration for a single query run."""

    prompt: str
    workspace: str | Path
    provider: str | None = None
    model: str | None = None
    tools: list[str] | None = None  # tool names to enable; None = all
    permission_mode: str = "dontAsk"
    max_turns: int = 20
    run_id: str | None = None
    debug_log_path: str | Path | None = None
    # Environment variables merged into the headless session's Bash
    # subprocess env. Values override inherited daemon env.
    env: dict[str, str] | None = None


@dataclass
class TextDelta:
    """Streaming text chunk."""

    content: str


@dataclass
class ToolCallEvent:
    """Tool call event from the agent."""

    tool_name: str
    params: dict[str, Any]
    tool_use_id: str | None = None
    _approved: bool | None = None
    _deny_reason: str | None = None

    @property
    def is_approved(self) -> bool | None:
        return self._approved


@dataclass
class ToolResultEvent:
    """Tool result event from the agent."""

    tool_name: str
    result: dict[str, Any]
    # F-49 Phase 0.1: pair this result with the originating ToolCallEvent.
    # Populated by convert_tool_event from the bridge dict; defaults to
    # None for events that lack an id.
    tool_use_id: str | None = None


@dataclass
class PhaseComplete:
    """One phase (multiple turns) finished."""

    phase: int
    turn_count: int


@dataclass
class TurnComplete:
    """One turn finished."""

    turn: int


@dataclass
class SessionComplete:
    """Session finished."""

    reason: str


QueryEvent = (
    TextDelta | ToolCallEvent | ToolResultEvent | TurnComplete | PhaseComplete | SessionComplete
)


class QueryRunner:
    """Execute a single prompt through ClawCodex query engine."""

    def __init__(self, config: QueryConfig) -> None:
        self.config = config

    async def stream(self) -> AsyncIterator[QueryEvent]:
        """Yield query events as they occur.

        Uses the headless runner registry under the hood, which dispatches
        to the configured backend (default: upstream headless entrypoint).
        The caller observes tool events via ``on_event`` without needing
        to import from upstream.
        """
        # Import the headless session runner — this stays off the upstream
        # import path at module-load time; the concrete implementation is
        # loaded lazily inside run_headless_session.
        from ..capabilities.headless_runner import HeadlessSessionOptions, run_headless_session

        debug_log_path = self.config.debug_log_path
        append_debug_event(
            debug_log_path,
            "query_runner.start",
            run_id=self.config.run_id,
            provider=self.config.provider,
            model=self.config.model,
            permission_mode=self.config.permission_mode,
            prompt_len=len(self.config.prompt),
            workspace=str(self.config.workspace),
            max_turns=self.config.max_turns,
        )

        event_queue: queue.Queue[Any] = queue.Queue()
        tool_event_count = 0
        last_event_at = time.monotonic()
        tool_names_by_id: dict[str, str] = {}

        def on_event(tool_event: Any) -> None:
            nonlocal tool_event_count, last_event_at
            try:
                tool_event_count += 1
                last_event_at = time.monotonic()
                kind = getattr(tool_event, "kind", None)
                tool_use_id = getattr(tool_event, "tool_use_id", None)
                tool_name = getattr(tool_event, "tool_name", "")
                if kind == "tool_use" and tool_use_id and tool_name:
                    tool_names_by_id[str(tool_use_id)] = str(tool_name)
                elif not tool_name and tool_use_id:
                    tool_name = tool_names_by_id.get(str(tool_use_id), "")
                is_error = getattr(tool_event, "is_error", False)
                error = getattr(tool_event, "error", None)
                append_debug_event(
                    debug_log_path,
                    "headless.event",
                    run_id=self.config.run_id,
                    kind=kind,
                    tool=tool_name,
                    tool_use_id=tool_use_id,
                    is_error=is_error,
                    error=str(error)[:500] if error is not None and is_error else None,
                )
                event_queue.put(tool_event)
            except Exception:
                pass

        stdout = io.StringIO()
        session_opts = HeadlessSessionOptions(
            prompt=self.config.prompt,
            workspace_root=Path(self.config.workspace),
            provider_name=self.config.provider,
            model=self.config.model,
            max_turns=self.config.max_turns,
            permission_mode=self.config.permission_mode,
            stdout=stdout,
            stderr=stdout,
            on_event=on_event,
            env=self.config.env or {},
        )

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, run_headless_session, session_opts)
        next_heartbeat_at = time.monotonic() + 30.0

        def convert_tool_event(ev: Any) -> QueryEvent | None:
            kind = getattr(ev, "kind", None)
            tool_name = getattr(ev, "tool_name", "")
            tool_input = getattr(ev, "tool_input", None)
            tool_use_id = getattr(ev, "tool_use_id", None)
            if kind == "tool_use" and tool_use_id and tool_name:
                tool_names_by_id[str(tool_use_id)] = str(tool_name)
            elif not tool_name and tool_use_id:
                tool_name = tool_names_by_id.get(str(tool_use_id), "")
            tool_output = getattr(ev, "tool_output", None)
            is_error = getattr(ev, "is_error", False)
            error = getattr(ev, "error", None)

            if kind == "tool_use":
                return ToolCallEvent(
                    tool_name=tool_name,
                    params=tool_input or {},
                    tool_use_id=tool_use_id,
                )
            if kind in {"tool_result", "tool_error"}:
                result = {
                    "output": tool_output,
                    "is_error": bool(is_error) or kind == "tool_error",
                }
                if error is not None:
                    result["error"] = error
                return ToolResultEvent(
                    tool_name=tool_name,
                    result=result,
                    tool_use_id=tool_use_id,
                )
            return None

        # Drain the event queue while the headless session runs in the background.
        # A short timeout lets us poll for completion without busy-waiting.
        #
        # F-108 P108-B: the polling loop also enforces ``_QUERY_TIMEOUT_S``
        # (default 300 s). ``asyncio.wait_for`` cannot cancel an executor
        # future — ``future.done()`` would stay False even after
        # ``wait_for`` raised — so the budget check lives INSIDE the
        # loop instead of wrapping the final ``await future``. On
        # timeout we break out and surface ``exit_code=124``.
        timeout_s = _QUERY_TIMEOUT_S
        loop_started_at = time.monotonic()
        timed_out = False
        while True:
            try:
                ev: Any = event_queue.get(timeout=0.05)
                event = convert_tool_event(ev)
                if event is not None:
                    yield event
            except queue.Empty:
                if future.done():
                    while True:
                        try:
                            ev = event_queue.get_nowait()
                        except queue.Empty:
                            break
                        event = convert_tool_event(ev)
                        if event is not None:
                            yield event
                    break
                now = time.monotonic()
                # F-108 P108-B: budget enforcement inside the polling
                # loop. Conventional GNU ``timeout`` exit code (124)
                # distinguishes "wall-clock budget exhausted" from
                # other non-zero exits.
                if timeout_s > 0 and (now - loop_started_at) >= timeout_s:
                    timed_out = True
                    break
                if now >= next_heartbeat_at:
                    append_debug_event(
                        debug_log_path,
                        "query_runner.heartbeat",
                        run_id=self.config.run_id,
                        future_done=future.done(),
                        seconds_since_last_event=round(now - last_event_at, 3),
                        stdout_len=len(stdout.getvalue()),
                        tool_events=tool_event_count,
                    )
                    next_heartbeat_at = now + 30.0
                await asyncio.sleep(0.01)

        if timed_out:
            # F-108 P108-B: headless future is still running on the
            # executor — we cannot kill it from Python — but the
            # caller sees a definitive ``SessionComplete`` and the
            # debug log carries enough context for postmortem.
            append_debug_event(
                debug_log_path,
                "query_runner.timeout",
                run_id=self.config.run_id,
                timeout_s=timeout_s,
                seconds_since_start=round(time.monotonic() - loop_started_at, 3),
                stdout_len=len(stdout.getvalue()),
            )
            exit_code = 124
        else:
            try:
                exit_code = await future
            except SystemExit as exc:
                code = exc.code
                exit_code = code if isinstance(code, int) else 1
        result_text = stdout.getvalue()
        if result_text:
            yield TextDelta(content=result_text)

        reason = "success" if exit_code == 0 else f"exit_code={exit_code}"
        yield SessionComplete(reason=reason)

    async def run(self) -> dict[str, Any]:
        """Run to completion, return final result."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        async for event in self.stream():
            if isinstance(event, TextDelta):
                text_parts.append(event.content)
            elif isinstance(event, ToolCallEvent):
                tool_calls.append({"name": event.tool_name, "params": event.params})
            elif isinstance(event, SessionComplete):
                return {
                    "text": "".join(text_parts),
                    "reason": event.reason,
                    "tool_calls": tool_calls,
                }
        return {"text": "".join(text_parts), "reason": "unknown", "tool_calls": tool_calls}
