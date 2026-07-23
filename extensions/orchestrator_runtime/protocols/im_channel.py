"""Orchestrator Runtime — IM Channel Protocol（Phase 1）。

声明 IM 平台集成的契约（Feishu / Slack / Telegram 等）。orchestrator
为每个 origin 装配一个 channel；channel 自己负责 poll/websocket
transport 与平台特定 card 渲染。

完整契约见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §4.4。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass(slots=True)
class ImInbound:
    """Mirrors ``clawcodex_ext.services.im_gateway.models.InboundMessage``
    shape (structurally)."""

    origin: str
    text: str
    issue_id: str | None = None
    thread_id: str | None = None
    sender_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImOutbound:
    """Mirrors ``clawcodex_ext.services.im_gateway.models.OutboundMessage``."""

    origin: str
    text: str
    issue_id: str | None = None
    card: dict[str, Any] | None = None  # platform-specific card payload


@runtime_checkable
class ImChannel(Protocol):
    """One integration with an IM platform (Feishu, Slack, Telegram…).

    The orchestrator wires one channel per origin; each channel handles
    its own poll/websocket transport.
    """

    channel_id: str

    async def deliver(self, message: ImOutbound) -> None:
        """Send ``message`` to the platform; raise on transport failure."""
        ...

    async def listen(self) -> AsyncIterator[ImInbound]:
        """Async generator of inbound messages from the platform."""
        ...

    async def close(self) -> None:
        """Release transport resources (websockets, etc.)."""
        ...


@runtime_checkable
class ImCommandRouter(Protocol):
    """Dispatch semantic commands (RETRY / FOLLOWUP / PAUSE / RESUME …)
    into orchestrator operations.

    Implementations may differ per channel; the orchestrator only depends
    on the contract. Mirrors ``clawcodex_ext.messaging.semantics.CommandRouter``.
    """

    async def dispatch(self, inbound: ImInbound) -> ImOutbound | None:
        """If ``inbound`` carries a recognised command, return response;
        otherwise return ``None`` (pass-through to orchestrator normal flow).
        """
        ...


__all__ = [
    "ImChannel",
    "ImCommandRouter",
    "ImInbound",
    "ImOutbound",
]
