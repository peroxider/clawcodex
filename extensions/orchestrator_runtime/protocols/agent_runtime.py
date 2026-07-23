"""Orchestrator Runtime — AgentRuntime Protocol（Phase 1）。

声明单轮多步 agent 异步流的契约。每次 ``stream()`` 产出事件直到
``SessionComplete`` 终止事件。 ``AgentRunner`` 通过 ``AgentRuntime``
接口调用具体后端（如 ClawcodexBackend 包装的 ``QueryRunner``，
或第三方 Aider / Continue 适配器）。

完整契约见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §4.1。
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator, Protocol, runtime_checkable

from .messages import AgentEvent


@runtime_checkable
class SessionContext(Protocol):
    """Per-stream session handle that ``AgentRuntime`` writes to.

    Implementations may back this with ``clawcodex_ext.agent.session.Session``
    (Phase 4 ClawcodexBackend) or a stub (test-only).
    """

    session_id: str
    workspace: Path

    def persist(self) -> None:
        """Flush in-memory state to disk / backend."""
        ...


@runtime_checkable
class AgentRuntime(Protocol):
    """One multi-turn agent execution; emits events until ``SessionComplete``.

    The orchestrator's :class:`AgentRunner` calls :meth:`stream` once per
    AgentSession; the runtime drives the conversation loop, tool execution,
    and emits events until :class:`SessionComplete`.

    Event sequence (semantic):

      - zero or more :class:`TextDelta`
      - zero or more interleave of :class:`ToolCallEvent` / :class:`ToolResultEvent`
      - zero or more :class:`PhaseComplete`
      - exactly one terminal :class:`SessionComplete` (success or failure)

    Notes:
      - Implementations MUST yield ``SessionComplete`` exactly once.
      - Errors during execution MUST yield ``SessionComplete(reason="error",
        final_text=str(exc))`` rather than raising.
    """

    async def stream(
        self,
        *,
        prompt: str,
        workspace: Path,
        provider_name: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        session_id: str | None = None,
        on_session: SessionContext | None = None,
    ) -> AsyncIterator[AgentEvent]:
        ...

    async def resume(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
    ) -> AsyncIterator[AgentEvent]:
        """Resume a previously persisted session.

        ``SessionComplete`` carries ``reason="resumed"`` on success.
        """
        ...


__all__ = ["AgentRuntime", "SessionContext"]
