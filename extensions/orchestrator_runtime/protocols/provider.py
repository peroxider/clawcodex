"""Orchestrator Runtime — LLMProvider marker Protocol（Phase 1）。

LLM provider 生命周期由 ``AgentRuntime`` 拥有，不在 orchestrator 协议
边界内。本 Protocol 仅作为「provider 标识」存在，避免 orchestrator
导入具体 provider 类。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Marker — the orchestrator never calls provider directly. It's passed
    by name to ``AgentRuntime.stream()``; AgentRuntime owns the provider
    lifecycle.
    """

    name: str
    model: str


__all__ = ["LLMProvider"]
