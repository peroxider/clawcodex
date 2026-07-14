"""Gateway IPC client — POSIX UDS client for REPL/orchestrator opt-in + control.

Connects to the gateway daemon's UDS socket, sends :class:`GatewayFrame`
lines, reads responses. ``register`` + periodic ``heartbeat`` keep the
peer online; ``deliver`` carries inbound text with layered ack. The
control helpers (:meth:`reload_channel`, :meth:`status`) drive
``channels restart`` / ``channels status`` against the running daemon.

Two directions:
  * request/response (register/heartbeat/control): ``_send`` writes a
    frame and awaits the matching reply, routed by a future keyed on
    ``message_id``.
  * server-pushed DELIVER frames: a background ``_read_loop`` dispatches
    them to the injected ``on_deliver`` callback (REPL/orchestrator
    consume inbound WeChat messages this way). ``send_outbound`` carries
    a reply back to the gateway for delivery to WeChat.

Heartbeat/reconnect (exp backoff 1s→30s, max 10 attempts) and delivery_id
dedup are wired for the P5 REPL wrapper; v1 control use is sync
request/response.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from .ipc_protocol import GatewayFrame, FrameType

logger = logging.getLogger(__name__)

OnDeliverFn = Callable[[GatewayFrame], Awaitable[None] | None]


class GatewayIpcClient:
    def __init__(
        self,
        socket_path: str | Path,
        *,
        instance_id: str = "client",
        on_deliver: OnDeliverFn | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.instance_id = instance_id
        self.on_deliver = on_deliver
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._seen_delivery_ids: set[str] = set()
        self._read_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[GatewayFrame]] = {}
        self._write_lock: asyncio.Lock | None = None  # created in connect()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_unix_connection(str(self.socket_path))
        self._write_lock = asyncio.Lock()
        logger.info("gateway ipc client connected: %s", self.socket_path)
        # Background read loop routes reply frames to pending requests and
        # server-pushed DELIVER frames to on_deliver.
        self._read_task = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with __import__("contextlib").suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with __import__("contextlib").suppress(ConnectionError, RuntimeError):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None
        # Release any waiters still blocked on a reply.
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_result(None)  # type: ignore[arg-type]
        self._pending.clear()
        logger.debug("gateway ipc client closed")

    async def _read_loop(self) -> None:
        if self._reader is None:
            return
        while not self._reader.at_eof():
            try:
                raw = await self._reader.readline()
            except (ConnectionError, asyncio.CancelledError):
                break
            if not raw:
                break
            try:
                frame = GatewayFrame.decode(raw)
            except ValueError:
                logger.debug("gateway ipc: dropping undecodable frame")
                continue
            self._dispatch_incoming(frame)

    def _dispatch_incoming(self, frame: GatewayFrame) -> None:
        """Route an incoming frame to a pending request future or on_deliver."""
        # Replies (ACK/NACK/EVENT-response) echo the original request's id in
        # ``delivery_id`` (acks) or ``message_id``. Try delivery_id first
        # because ACK frames carry a fresh message_id of their own.
        fut = None
        for key in (frame.delivery_id, frame.message_id):
            if key:
                fut = self._pending.pop(key, None)
                if fut is not None:
                    break
        if fut is not None and not fut.done():
            fut.set_result(frame)
            return
        # Server-pushed DELIVER (inbound WeChat message for this opt-in host).
        if frame.type is FrameType.DELIVER and self.on_deliver is not None:
            try:
                result = self.on_deliver(frame)
                if result is not None:
                    asyncio.ensure_future(result)
            except Exception:  # noqa: BLE001
                logger.exception("gateway ipc: on_deliver callback failed")

    async def _send(self, frame: GatewayFrame) -> GatewayFrame | None:
        """Write a frame and await its reply (routed by the read loop).

        The server echoes the reply id in either ``message_id`` or
        ``delivery_id`` depending on frame kind (REGISTER acks echo
        ``message_id``; DELIVER/EVENT acks echo ``delivery_id``), so we
        register the pending future under both keys when present.

        Transport-level errors (BrokenPipeError, ConnectionResetError)
        are caught and return ``None`` so callers can react gracefully
        (reconnect, queue for later) instead of receiving a raw
        exception — the gateway and orchestrator are decoupled and
        either may be stopped independently.
        """
        if self._writer is None:
            raise RuntimeError("not connected")
        keys = [k for k in (frame.message_id, frame.delivery_id) if k]
        fut: asyncio.Future[GatewayFrame] = asyncio.get_running_loop().create_future()
        for k in keys:
            self._pending[k] = fut
        # Serialize writes: asyncio StreamWriter is not safe to write from
        # multiple tasks concurrently (heartbeat vs send_outbound vs _send).
        try:
            async with self._write_lock:
                self._writer.write(frame.encode())
                await self._writer.drain()
        except (ConnectionError, BrokenPipeError) as exc:
            # The gateway socket is gone (gateway stopped, process killed,
            # or network dropped). Clean up pending futures and return None
            # so the caller can reconnect — never propagate transport errors.
            for k in keys:
                self._pending.pop(k, None)
            logger.debug("gateway ipc: send failed (connection lost): %s", exc)
            return None
        if not keys:
            return None  # fire-and-forget frame (no reply expected)
        try:
            return await asyncio.wait_for(fut, timeout=5.0)
        except asyncio.TimeoutError:
            for k in keys:
                self._pending.pop(k, None)
            logger.debug("gateway ipc: reply timed out for keys=%s", keys)
            return None

    async def _write_frame_no_reply(self, frame: GatewayFrame) -> None:
        """Write a fire-and-forget frame without waiting on the read loop."""
        if self._writer is None:
            raise RuntimeError("not connected")
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        try:
            async with self._write_lock:
                self._writer.write(frame.encode())
                await self._writer.drain()
        except (ConnectionError, BrokenPipeError) as exc:
            logger.debug("gateway ipc: send failed (connection lost): %s", exc)
            return None

    async def register(
        self, *, session_id: str, origin: str, capabilities: list[str] | None = None
    ) -> GatewayFrame | None:
        return await self._send(
            GatewayFrame.register(
                session_id=session_id, origin=origin, capabilities=capabilities or []
            )
        )

    async def reconnect_until_registered(
        self,
        *,
        session_id: str,
        origin: str,
        capabilities: list[str] | None = None,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        max_attempts: int = 10,
    ) -> GatewayFrame | None:
        """Reconnect with exponential backoff and re-register this client.

        This is intentionally limited to connection restoration. Messages that
        arrived while the opt-in target was offline are not replayed by the
        gateway, so reconnecting only rebuilds the active binding.
        """
        delay = max(0.0, base_delay)
        max_delay = max(delay, max_delay)
        for attempt in range(max_attempts):
            try:
                await self.close()
                await self.connect()
                response = await self.register(
                    session_id=session_id,
                    origin=origin,
                    capabilities=capabilities,
                )
                if response is not None and response.ack_layer == "accepted":
                    return response
            except Exception:  # noqa: BLE001
                logger.debug(
                    "gateway ipc: reconnect attempt %d/%d failed",
                    attempt + 1,
                    max_attempts,
                    exc_info=True,
                )
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
                delay = min(delay * 2 if delay else base_delay, max_delay)
        logger.warning(
            "gateway ipc: reconnect exhausted after %d attempts (session=%s)",
            max_attempts,
            session_id[:16],
        )
        return None

    async def heartbeat(self) -> GatewayFrame | None:
        return await self._send(GatewayFrame.heartbeat(session_id=self.instance_id))

    async def unregister(self, session_id: str | None = None) -> GatewayFrame | None:
        return await self._send(
            GatewayFrame(type=FrameType.UNREGISTER, session_id=session_id or self.instance_id)
        )

    async def deliver(
        self,
        *,
        delivery_id: str,
        session_id: str,
        origin: str,
        text: str,
        semantic: str | None = None,
        context_token: str | None = None,
    ) -> GatewayFrame | None:
        if delivery_id in self._seen_delivery_ids:
            return None  # idempotent: don't redeliver
        response = await self._send(
            GatewayFrame.deliver(
                delivery_id=delivery_id,
                session_id=session_id,
                origin=origin,
                text=text,
                semantic=semantic,
                context_token=context_token,
            )
        )
        if response is not None and response.ack_layer in {"accepted", "enqueued", "processed"}:
            self._seen_delivery_ids.add(delivery_id)
        return response

    async def ack(
        self, *, delivery_id: str, layer: str, message: str | None = None
    ) -> GatewayFrame | None:
        await self._write_frame_no_reply(
            GatewayFrame.ack(delivery_id=delivery_id, layer=layer, message=message)
        )
        return None

    async def send_outbound(
        self,
        *,
        origin: str,
        text: str,
        context_token: str | None = None,
        metadata: dict[str, Any] | None = None,
        semantic_tags: list[str] | None = None,
        in_reply_to: str | None = None,
    ) -> GatewayFrame | None:
        """Send a reply back to the gateway for delivery to the IM origin.

        The server replies with ACK/NACK, so callers get an observable result
        while still treating delivery as best-effort at the IM channel layer.
        """
        if self._writer is None:
            raise RuntimeError("not connected")
        frame = GatewayFrame.outbound(
            origin=origin,
            text=text,
            context_token=context_token,
            metadata=metadata,
            semantic_tags=semantic_tags,
            in_reply_to=in_reply_to,
        )
        response = await self._send(frame)
        if response is None:
            logger.warning("gateway ipc: OUTBOUND timed out origin=%s", origin[:24])
        elif response.type is FrameType.NACK:
            logger.warning(
                "gateway ipc: OUTBOUND rejected origin=%s reason=%s",
                origin[:24],
                response.reason or "",
            )
        else:
            logger.debug("gateway ipc: sent OUTBOUND origin=%s len=%d", origin[:24], len(text))
        return response

    async def complete_processing(
        self,
        *,
        message_id: str,
        outcome: str,
        reason: str | None = None,
    ) -> GatewayFrame | None:
        """Report a terminal processing outcome for a pushed DELIVER frame."""
        await self._write_frame_no_reply(
            GatewayFrame.processing_complete(
                message_id=message_id,
                outcome=outcome,
                reason=reason,
            )
        )
        return None

    async def reload_channel(self, name: str) -> GatewayFrame | None:
        return await self._send(
            GatewayFrame.event(event_type="control.reload", payload={"channel": name})
        )

    async def unbind_origin(self, origin: str) -> GatewayFrame | None:
        return await self._send(
            GatewayFrame.event(event_type="control.unbind", payload={"origin": origin})
        )

    async def status(self) -> dict | None:
        resp = await self._send(GatewayFrame.event(event_type="control.status"))
        if resp is not None and resp.payload is not None:
            return resp.payload
        return None

    async def __aenter__(self) -> GatewayIpcClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
