"""ClawcodexImChannel — concrete ``ImChannel`` + ``ImCommandRouter`` Protocol adapter.

薄包装 ``extensions.orchestrator.im_gateway_client.OrchestratorGatewayClient``，
让 ``im_gateway_client`` 的 L89-92 / L152 / L365 三处 lazy import 不再直连
``clawcodex_ext.{services.im_gateway.models, messaging.semantics, entrypoints.orchestrator}``。

设计
====

* ``deliver()`` / ``listen()`` / ``close()`` 三个 ``ImChannel`` 方法 1:1
  转发到 ``OrchestratorGatewayClient`` 的 ``send_outbound`` /
  ``dispatch`` / 资源释放路径（close 暂为 no-op，由 orchestrator 生命周期接管）。
* ``ImCommandRouter.dispatch()`` 转发到 ``OrchestratorGatewayClient.dispatch()``。
* Inbound 形态转换：``InboundMessage`` (上游 dataclass) → ``ImInbound``
  (Protocol dataclass)；Outbound 反向。
* **不在 Commit 1 接入 im_gateway_client** —— Commit 2 才注入。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from extensions.orchestrator_runtime.protocols.im_channel import (
    ImChannel,
    ImCommandRouter,
    ImInbound,
    ImOutbound,
)


def _inbound_from_upstream(msg: Any) -> ImInbound:
    """Convert upstream ``InboundMessage`` → ``ImInbound``.

    Defensive attribute reads; missing fields fall back to empty defaults.
    """
    sem = getattr(msg, "semantic", None)
    sem_kind = getattr(sem, "kind", None) if sem is not None else None
    metadata: dict[str, Any] = {}
    if sem is not None:
        metadata["semantic_kind"] = sem_kind
        # Preserve any additional semantic fields the upstream defines.
        for attr in ("command", "args", "payload"):
            if hasattr(sem, attr):
                metadata[f"semantic_{attr}"] = getattr(sem, attr)
    return ImInbound(
        origin=getattr(msg, "origin", "") or "",
        text=getattr(msg, "text", "") or "",
        issue_id=getattr(msg, "issue_id", None),
        thread_id=getattr(msg, "thread_id", None),
        sender_id=getattr(msg, "sender_id", None),
        metadata=metadata,
    )


def _outbound_to_upstream(out: ImOutbound) -> dict[str, Any]:
    """Convert ``ImOutbound`` → dict compatible with upstream ``send_outbound``."""
    return {
        "origin": out.origin,
        "text": out.text,
        "issue_id": out.issue_id,
        "card": out.card or {},
    }


class ClawcodexImChannel(ImChannel, ImCommandRouter):
    """Adapter over ``OrchestratorGatewayClient``.

    Constructed lazily inside ``OrchestratorGatewayClient.__init__`` via the
    new ``im_channel=`` kw arg; does not own its gateway lifetime.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    @property
    def channel_id(self) -> str:
        return getattr(self._gateway, "origin", "") or "clawcodex-im"

    async def deliver(self, message: ImOutbound) -> None:
        # ``OrchestratorGatewayClient.send_outbound`` is the canonical writer;
        # it handles queueing + retry + backoff internally.
        send = getattr(self._gateway, "send_outbound", None)
        if send is None:
            return
        send(_outbound_to_upstream(message))

    async def listen(self) -> AsyncIterator[ImInbound]:
        # ``OrchestratorGatewayClient`` is a *server-pushed* model via the
        # ``_on_pushed_deliver`` callback. ``listen()`` here is a no-op async
        # iterator that yields nothing — actual inbound delivery happens via
        # the callback path the gateway registered against ``ipc_client``.
        if False:  # pragma: no cover — explicit no-op
            yield ImInbound(origin="", text="")
        return

    async def close(self) -> None:
        # No explicit close on OrchestratorGatewayClient — orchestrator owns
        # the gateway lifecycle. Keep as no-op for Protocol conformance.
        return None

    async def dispatch(self, inbound: ImInbound) -> ImOutbound | None:
        """ImCommandRouter.dispatch — forward to gateway ``dispatch()``."""
        # Convert ImInbound → upstream InboundMessage-shaped dict; the gateway
        # dispatch() expects an InboundMessage instance, but its internal
        # dispatch path reads attributes (origin / text / semantic). We pass
        # a lightweight shim that satisfies duck-typing.
        sem_kind = inbound.metadata.get("semantic_kind") if inbound.metadata else None
        sem_obj = _SemanticShim(kind=sem_kind) if sem_kind else None
        upstream_msg = _InboundShim(
            origin=inbound.origin,
            text=inbound.text,
            issue_id=inbound.issue_id,
            thread_id=inbound.thread_id,
            sender_id=inbound.sender_id,
            semantic=sem_obj,
        )
        result = self._gateway.dispatch(upstream_msg)
        if result is None:
            return None
        if isinstance(result, ImOutbound):
            return result
        # Convert upstream return → ImOutbound
        return ImOutbound(
            origin=inbound.origin,
            text=getattr(result, "text", "") or "",
            issue_id=inbound.issue_id,
            card=getattr(result, "card", None),
        )


# ─── Lightweight shims (duck-typed to upstream ``InboundMessage`` /
#     ``MessageSemantics``; defined locally to avoid importing upstream).


class _SemanticShim:
    def __init__(self, kind: str | None) -> None:
        self.kind = kind


class _InboundShim:
    def __init__(
        self,
        *,
        origin: str,
        text: str,
        issue_id: str | None,
        thread_id: str | None,
        sender_id: str | None,
        semantic: Any | None,
    ) -> None:
        self.origin = origin
        self.text = text
        self.issue_id = issue_id
        self.thread_id = thread_id
        self.sender_id = sender_id
        self.semantic = semantic


__all__ = ["ClawcodexImChannel"]