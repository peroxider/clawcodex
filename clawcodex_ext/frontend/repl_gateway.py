"""ReplGatewayClient — REPL opt-in UDS client wrapping ``_enqueue_prompt`` (P5).

Lives in ``clawcodex_ext/frontend/`` and mounts via the existing
``install_repl_extensions`` hook (no src change). It:

  * connects to the gateway daemon UDS and registers the REPL session
    as the opt-in target for an origin (overriding the default route)
  * heartbeats + reconnects (exp backoff) so the gateway sees it online
  * on inbound ``followUp``/``newPrompt``, checks the REPL prompt queue
    capacity and dedups by ``delivery_id`` before calling
    ``repl._enqueue_prompt(text)`` — never silently drops when the
    ``deque(maxlen=100)`` is full (rejects + ack instead)
  * acks in layers: ``accepted`` on receive, ``enqueued`` after a
    successful ``_enqueue_prompt``

The wrapper takes injectable ``enqueue`` / ``queue_size`` callables so it
is unit-testable without a live REPL.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Awaitable, Callable

from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient
from clawcodex_ext.services.im_gateway.ipc_protocol import GatewayFrame

logger = logging.getLogger(__name__)

EnqueueFn = Callable[[str], None]
QueueSizeFn = Callable[[], int]
WakeFn = Callable[[], None]
ControlHandlerFn = Callable[[str, str | None], bool]
PermissionProbeFn = Callable[[str], bool]

_REPL_CONTROL_COMMANDS = frozenset({"/stop"})


class ReplGatewayClient:
    def __init__(
        self,
        socket_path: str,
        *,
        session_id: str,
        origin: str,
        enqueue: EnqueueFn,
        queue_size: QueueSizeFn,
        queue_capacity: int = 100,
        instance_id: str | None = None,
        wake: WakeFn | None = None,
        control_handler: ControlHandlerFn | None = None,
        permission_probe: PermissionProbeFn | None = None,
    ) -> None:
        self._socket_path = socket_path
        self._session_id = session_id
        self._origin = origin
        self._enqueue = enqueue
        self._queue_size = queue_size
        self._capacity = queue_capacity
        self._instance_id = instance_id or session_id
        self._permission_probe = permission_probe
        # Wake the REPL's blocked prompt loop so an enqueued IM prompt is
        # drained on the next loop iteration. Without this the prompt sits in
        # ``_queued_prompts`` while the main loop is stuck in
        # ``prompt_async('❯ ')`` (the only other wake, ``_watch_outbox``,
        # fires solely on cron outbox events) — the message is never
        # displayed, processed, or replied to.
        self._wake: WakeFn | None = wake
        self._control_handler = control_handler
        # The IPC client's on_deliver fires when the gateway pushes an inbound
        # WeChat message for this origin. Route it to self.deliver, which does
        # dedup / capacity check / enqueue / ack.
        self._client = GatewayIpcClient(
            socket_path,
            instance_id=self._instance_id,
            on_deliver=self._on_pushed_deliver,
        )
        self._seen: set[str] = set()
        self._reply_origins: deque[str] = deque()
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def _on_pushed_deliver(self, frame) -> None:
        """Server-pushed DELIVER callback: enqueue into the REPL prompt queue."""
        delivery_id = frame.delivery_id or frame.message_id or ""
        text = frame.text or ""
        logger.info(
            "repl_gateway: inbound push delivery_id=%s len=%d → enqueue",
            delivery_id[:16],
            len(text),
        )
        try:
            await self.deliver(
                delivery_id=delivery_id,
                text=text,
                origin=frame.origin,
                semantic=frame.semantic,
            )
        except QueueFull:
            logger.warning("repl_gateway: queue full, rejected delivery_id=%s", delivery_id[:16])
        except Exception:  # noqa: BLE001
            logger.exception("repl_gateway: deliver failed delivery_id=%s", delivery_id[:16])

    async def connect(self) -> None:
        await self._client.connect()
        await self._client.register(
            session_id=self._session_id, origin=self._origin, capabilities=["outbound_text"]
        )

    async def close(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        await self._client.close()

    async def start_heartbeat(self, interval: float = 30.0) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def _heartbeat_loop(self, interval: float) -> None:
        while True:
            try:
                await self._client.heartbeat()
            except Exception:  # noqa: BLE001
                logger.debug("heartbeat failed", exc_info=True)
            await asyncio.sleep(interval)

    def can_enqueue(self) -> bool:
        """Reject before the deque(maxlen) silently drops the oldest message."""
        return self._queue_size() < self._capacity

    async def deliver(
        self,
        *,
        delivery_id: str,
        text: str,
        origin: str | None = None,
        semantic: str | None = None,
    ) -> GatewayFrame | None:
        """Enqueue a follow-up/newPrompt into the REPL, layered ack.

        Returns the ack frame from the gateway (or None if deduped).
        Raises ``QueueFull`` if the REPL prompt queue is at capacity so the
        gateway acks ``accepted`` (rejected) rather than silently dropping.
        """
        if delivery_id in self._seen:
            return None
        # A pending REPL permission wait accepts a WeChat reply (menu
        # number/letter, or /stop→deny) as the decision. This MUST take
        # priority over the control/enqueue paths so a "1"/"y" reply is
        # consumed as the permission choice instead of being queued as a
        # new prompt for the next turn.
        if self._permission_probe is not None and self._permission_probe(text):
            self._seen.add(delivery_id)
            return await self._client.ack(
                delivery_id=delivery_id, layer="processed", message="permission reply"
            )
        if self._is_priority_control(text, semantic):
            self._seen.add(delivery_id)
            handled = False
            if self._control_handler is not None:
                handled = bool(self._control_handler(text, origin))
            message = "control dispatched" if handled else "control ignored"
            return await self._client.ack(
                delivery_id=delivery_id, layer="processed", message=message
            )
        if not self.can_enqueue():
            raise QueueFull(f"REPL prompt queue at capacity ({self._capacity})")
        self._seen.add(delivery_id)
        if origin:
            self._reply_origins.append(origin)
        self._enqueue(text)
        # Wake the REPL prompt loop so it iterates and drains the just-enqueued
        # prompt instead of staying blocked on ``prompt_async('❯ ')``.
        if self._wake is not None:
            try:
                self._wake()
            except Exception:  # noqa: BLE001
                logger.debug("repl_gateway: wake callback failed", exc_info=True)
        # acknowledge enqueued back to the gateway
        return await self._client.ack(delivery_id=delivery_id, layer="enqueued", message="enqueued")

    @staticmethod
    def _is_priority_control(text: str, semantic: str | None) -> bool:
        normalized = (text or "").strip().split(maxsplit=1)[0].lower()
        if normalized in _REPL_CONTROL_COMMANDS:
            return True
        return (semantic or "").strip().lower() == "interrupt"

    def next_reply_origin(self, fallback: str) -> str:
        """Return the origin that should receive the next assistant reply."""
        if self._reply_origins:
            return self._reply_origins.popleft()
        return fallback

    def peek_reply_origin(self) -> str | None:
        """Return the current IM origin without consuming the final-reply slot."""
        if self._reply_origins:
            return self._reply_origins[0]
        return None

    def pop_reply_origin(self) -> str | None:
        """Pop the IM origin that triggered the current assistant turn.

        Returns None when the deque is empty — the caller can use this to
        distinguish IM-driven turns (populated by ``deliver()``) from
        keyboard-initiated turns (empty deque). Only IM-driven turns
        should send an OUTBOUND reply back to WeChat.
        """
        if self._reply_origins:
            return self._reply_origins.popleft()
        return None


class QueueFull(Exception):
    """REPL prompt queue is at capacity — reject rather than silently drop."""


__all__ = [
    "EnqueueFn",
    "PermissionProbeFn",
    "QueueFull",
    "QueueSizeFn",
    "ReplGatewayClient",
    "WakeFn",
]
