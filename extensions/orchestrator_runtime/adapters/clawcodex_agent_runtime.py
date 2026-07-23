"""ClawcodexAgentRuntime — concrete ``AgentRuntime`` Protocol adapter.

包装 ``extensions.api.query.QueryRunner``，把它的 ``QueryEvent`` 流
（TextDelta / ToolCallEvent / ToolResultEvent / PhaseComplete / TurnComplete /
SessionComplete）逐个映射到 ``extensions.orchestrator_runtime.protocols.messages``
的 sum-type ``AgentEvent``。

设计
====

* **不在 Commit 1 接入 agent_runner** —— ``AgentRunner`` 仍直接持有
  ``QueryRunner``。Commit 2 才把 13 处 lazy import 中的 ``extensions.api.query``
  ``isinstance`` 检查切到 ``orchestrator_runtime.protocols.messages`` 形态。
* 本适配器作为**参考实现**，未来若需切到独立后端（Aider / Continue / etc.）
  可直接复用 1:1 事件映射。
* ``stream()`` 与 ``resume()`` 都委托给 ``QueryRunner``；构造时接收
  ``QueryConfig``，``stream()`` 每次调用都新建 ``QueryRunner``（与上游语义一致）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from extensions.orchestrator_runtime.protocols.agent_runtime import (
    AgentRuntime,
    SessionContext,
)
from extensions.orchestrator_runtime.protocols.messages import (
    AgentEvent,
    PhaseComplete as ProtocolPhaseComplete,
    SessionComplete as ProtocolSessionComplete,
    TextDelta as ProtocolTextDelta,
    ToolCallEvent as ProtocolToolCallEvent,
    ToolResultEvent as ProtocolToolResultEvent,
)


def _map_query_event(event: Any) -> AgentEvent:
    """Map one ``extensions.api.query.QueryEvent`` to ``AgentEvent``.

    Type-discriminated dispatch (avoids attribute-name drift between the two
    dataclass hierarchies).
    """
    cls_name = type(event).__name__
    if cls_name == "TextDelta":
        # upstream: TextDelta(content: str)
        return AgentEvent(
            type="text_delta",
            payload=ProtocolTextDelta(text=getattr(event, "content", "")),
        )
    if cls_name == "ToolCallEvent":
        # upstream: ToolCallEvent(tool_name, params, tool_use_id=None, ...)
        return AgentEvent(
            type="tool_call",
            payload=ProtocolToolCallEvent(
                tool_name=getattr(event, "tool_name", ""),
                tool_input=dict(getattr(event, "params", {}) or {}),
                call_id=getattr(event, "tool_use_id", "") or "",
            ),
        )
    if cls_name == "ToolResultEvent":
        # upstream: ToolResultEvent(tool_name, result, tool_use_id=None)
        return AgentEvent(
            type="tool_result",
            payload=ProtocolToolResultEvent(
                call_id=getattr(event, "tool_use_id", "") or "",
                output=getattr(event, "result", None),
                is_error=False,
            ),
        )
    if cls_name == "PhaseComplete":
        # upstream: PhaseComplete(phase: int, turn_count: int)
        # protocol: PhaseComplete(phase: str, cost=0.0, turn_count=0)
        return AgentEvent(
            type="phase_complete",
            payload=ProtocolPhaseComplete(
                phase=str(getattr(event, "phase", "")),
                turn_count=int(getattr(event, "turn_count", 0)),
            ),
        )
    if cls_name == "TurnComplete":
        # TurnComplete(turn: int) — fold into a synthetic PhaseComplete.
        return AgentEvent(
            type="phase_complete",
            payload=ProtocolPhaseComplete(
                phase="turn",
                turn_count=int(getattr(event, "turn", 0)),
            ),
        )
    if cls_name == "SessionComplete":
        # SessionComplete(reason: str)
        return AgentEvent(
            type="session_complete",
            payload=ProtocolSessionComplete(reason=getattr(event, "reason", "")),
        )
    # Unknown event — drop with a generic phase_complete so callers see it.
    return AgentEvent(
        type="phase_complete",
        payload=ProtocolPhaseComplete(phase=cls_name or "unknown"),
    )


class ClawcodexAgentRuntime(AgentRuntime):
    """Adapter that wraps ``extensions.api.query.QueryRunner``."""

    def __init__(self, config_factory: Any | None = None) -> None:
        """``config_factory(prompt, workspace, provider_name, model, tools,
        session_id) -> QueryConfig`` lets callers customise QueryConfig
        construction; default factory builds a vanilla QueryConfig.
        """
        self._config_factory = config_factory or _default_query_config_factory

    def _build_runner(
        self,
        *,
        prompt: str,
        workspace: Path,
        provider_name: str | None,
        model: str | None,
        tools: list[str] | None,
        session_id: str | None,
    ) -> Any:
        from extensions.api.query import QueryRunner

        config = self._config_factory(
            prompt=prompt,
            workspace=workspace,
            provider_name=provider_name,
            model=model,
            tools=tools,
            session_id=session_id,
        )
        return QueryRunner(config)

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
        runner = self._build_runner(
            prompt=prompt,
            workspace=workspace,
            provider_name=provider_name,
            model=model,
            tools=tools,
            session_id=session_id,
        )
        async for event in runner.stream():
            yield _map_query_event(event)

    async def resume(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
    ) -> AsyncIterator[AgentEvent]:
        # QueryRunner does not have a separate ``resume``; callers resume
        # by passing ``session_id`` into ``QueryConfig`` and re-``stream()``.
        # Default to that behaviour.
        async for event in self.stream(
            prompt=prompt,
            workspace=workspace,
            session_id=session_id,
        ):
            yield event


def _default_query_config_factory(
    *,
    prompt: str,
    workspace: Path,
    provider_name: str | None,
    model: str | None,
    tools: list[str] | None,
    session_id: str | None,
) -> Any:
    """Build a default ``QueryConfig`` mirroring agent_runner's typical call."""
    from extensions.api.query import QueryConfig

    return QueryConfig(
        prompt=prompt,
        workspace=str(workspace),
        provider=provider_name,
        model=model,
        tools=tools,
        run_id=session_id,
    )


__all__ = ["ClawcodexAgentRuntime"]