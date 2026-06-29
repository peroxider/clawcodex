"""Gateway IPC server — POSIX UDS handler for the GatewayIpcProtocol.

A raw :func:`asyncio.start_unix_server` reading newline-delimited
:class:`GatewayFrame` JSON. Handles ``register`` (record peer + ack
``accepted``), ``heartbeat`` (refresh last_seen), ``deliver`` (route to
the inbound dispatcher + ack ``enqueued``), and ``event`` control frames
(``control.reload`` → ``gateway.reload_channel``, ``control.status`` →
health). Per-peer ``last_seen`` drives offline detection (P4 heartbeat
contract). v1 is POSIX/WSL/Git Bash only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from .ipc_protocol import GatewayFrame, FrameType
from .origin_utils import (
    configured_wechat_channel as _configured_wechat_channel,
    is_concrete_wechat_direct_origin as _is_concrete_wechat_direct_origin,
    resolve_origin as _resolve_origin,
    wechat_adapter as _wechat_adapter,
)

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_SECONDS = 60.0


class GatewayIpcServer:
    def __init__(
        self,
        socket_path: str | Path,
        gateway,
        *,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
        clock=time.time,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.gateway = gateway
        self._heartbeat_timeout = heartbeat_timeout
        self._clock = clock
        self._server: asyncio.AbstractServer | None = None
        self._peers: dict[
            str, dict[str, Any]
        ] = {}  # session_id -> {writer, last_seen, capabilities}
        self._writer_locks: dict[asyncio.StreamWriter, asyncio.Lock] = {}

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self.socket_path)
        )

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for info in list(self._peers.values()):
            writer = info.get('writer')
            if writer is not None:
                writer.close()
                with __import__('contextlib').suppress(ConnectionError, RuntimeError):
                    await writer.wait_closed()
        self._peers.clear()
        self._writer_locks.clear()
        with __import__('contextlib').suppress(FileNotFoundError):
            self.socket_path.unlink()

    @property
    def connected_count(self) -> int:
        return len(self._peers)

    def peer_sessions(self) -> list[str]:
        return list(self._peers.keys())

    def is_online(self, session_id: str) -> bool:
        info = self._peers.get(session_id)
        if info is None:
            return False
        return (self._clock() - info.get('last_seen', 0)) < self._heartbeat_timeout

    def peers_snapshot(self) -> list[dict[str, Any]]:
        peers: list[dict[str, Any]] = []
        for session_id, info in self._peers.items():
            origin = str(info.get('origin') or '')
            capabilities = list(info.get('capabilities') or [])
            peers.append(
                {
                    'session_id': session_id,
                    'origin': origin,
                    'host_type': _host_type(session_id, capabilities),
                    'online': self.is_online(session_id),
                }
            )
        return peers

    async def push_deliver(
        self,
        *,
        origin: str,
        delivery_id: str,
        text: str,
        semantic: str | None = None,
    ) -> bool:
        """Push an inbound message to the opt-in peer bound to ``origin``.

        Looks up the origin's bound ``session_id`` via the gateway binding
        policy, finds the connected peer writer, and writes a DELIVER frame.
        Returns True if a live peer received the push, False otherwise (no
        binding or peer offline — the caller falls back to the default host).
        """
        entry = None
        if hasattr(self.gateway, 'binding'):
            entry = self.gateway.binding.get(origin)
        if entry is None:
            logger.debug('gateway ipc: push_deliver no binding for origin=%s', origin[:24])
            return False
        session_id = entry.target.session_id
        info = self._peers.get(session_id)
        if info is None:
            logger.debug('gateway ipc: push_deliver peer %s not connected', session_id[:16])
            return False
        frame = GatewayFrame.deliver(
            delivery_id=delivery_id,
            session_id=session_id,
            origin=origin,
            text=text,
            semantic=semantic,
        )
        await self._send(info['writer'], frame)
        logger.info(
            'gateway ipc: pushed DELIVER origin=%s session=%s delivery_id=%s',
            origin[:24],
            session_id[:16],
            delivery_id[:16],
        )
        return True

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_session: str | None = None
        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    frame = GatewayFrame.decode(raw)
                except ValueError:
                    continue
                if frame.type is FrameType.REGISTER and frame.session_id:
                    peer_session = frame.session_id
                    existing = self._peers.get(peer_session)
                    if existing is not None and existing.get('writer') is not writer:
                        await self._disconnect_peer(peer_session, existing)
                    if frame.origin:
                        await self._disconnect_conflicting_peers(frame.origin, frame.session_id)
                    host_type = _host_type(frame.session_id, frame.capabilities)
                    self._peers[peer_session] = {
                        'writer': writer,
                        'last_seen': self._clock(),
                        'capabilities': list(frame.capabilities),
                        'origin': frame.origin,
                    }
                    if frame.origin and hasattr(self.gateway, 'binding'):
                        from .models import SessionTarget

                        self.gateway.binding.bind(
                            frame.origin,
                            SessionTarget(
                                session_id=frame.session_id,
                                host_type=host_type,
                            ),
                        )
                    logger.info(
                        'gateway ipc: REGISTER session=%s host_type=%s origin=%s',
                        frame.session_id[:24],
                        host_type,
                        (frame.origin or '')[:32],
                    )
                    await self._send(
                        writer,
                        GatewayFrame.ack(
                            delivery_id=frame.message_id,
                            layer='accepted',
                            message='registered',
                        ),
                    )
                    continue
                if peer_session is not None:
                    info = self._peers.get(peer_session)
                    if info is None or info.get('writer') is not writer:
                        peer_session = None
                    else:
                        info['last_seen'] = self._clock()
                response = await self._dispatch(frame, peer_session, writer)
                if response is not None:
                    await self._send(writer, response)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if peer_session is not None:
                info = self._peers.get(peer_session)
                if info is not None and info.get('writer') is writer:
                    self._peers.pop(peer_session, None)
                    origin = info.get('origin')
                    if origin and hasattr(self.gateway, 'binding'):
                        self.gateway.binding.mark_offline(origin, session_id=peer_session)
            writer.close()
            with __import__('contextlib').suppress(ConnectionError, RuntimeError):
                await writer.wait_closed()

    async def _send(self, writer: asyncio.StreamWriter, frame: GatewayFrame) -> None:
        # Serialize writes per writer: _handle_client (ACK/NACK) and
        # push_deliver (pushed DELIVER) can write to the same writer
        # concurrently; StreamWriter is not safe for concurrent writes.
        lock = self._writer_locks.get(writer)
        if lock is None:
            lock = asyncio.Lock()
            self._writer_locks[writer] = lock
        try:
            async with lock:
                writer.write(frame.encode())
                await writer.drain()
        except (ConnectionError, RuntimeError):
            pass

    async def _dispatch(
        self, frame: GatewayFrame, peer_session: str | None, writer: asyncio.StreamWriter
    ) -> GatewayFrame | None:
        if frame.type is FrameType.HEARTBEAT:
            return GatewayFrame.ack(
                delivery_id=frame.message_id, layer='accepted', message='heartbeat'
            )
        if frame.type is FrameType.DELIVER:
            if peer_session is None:
                return GatewayFrame.nack(
                    delivery_id=frame.delivery_id or frame.message_id,
                    reason='peer not registered',
                )
            return await self._handle_deliver(frame)
        if frame.type is FrameType.OUTBOUND:
            return await self._handle_outbound(frame)
        if frame.type is FrameType.EVENT:
            return await self._handle_event(frame)
        if frame.type is FrameType.UNREGISTER:
            if peer_session is not None:
                info = self._peers.pop(peer_session, None)
                origin = info.get('origin') if info else None
                if origin and hasattr(self.gateway, 'binding'):
                    self.gateway.binding.terminate(origin, session_id=peer_session)
            return GatewayFrame.ack(
                delivery_id=frame.message_id, layer='accepted', message='unregistered'
            )
        return None

    async def _disconnect_conflicting_peers(self, origin: str, session_id: str) -> None:
        for existing_session, info in list(self._peers.items()):
            if existing_session == session_id:
                continue
            existing_origin = str(info.get('origin') or '')
            if not _same_exclusive_origin_group(origin, existing_origin):
                continue
            await self._disconnect_peer(existing_session, info)
            logger.info(
                'gateway ipc: disconnected previous peer session=%s origin=%s',
                existing_session[:16],
                existing_origin[:24],
            )

    async def _disconnect_matching_peers(self, origin: str) -> None:
        for existing_session, info in list(self._peers.items()):
            existing_origin = str(info.get('origin') or '')
            if not _same_exclusive_origin_group(origin, existing_origin):
                continue
            await self._disconnect_peer(existing_session, info)
            logger.info(
                'gateway ipc: disconnected peer via unbind session=%s origin=%s',
                existing_session[:16],
                existing_origin[:24],
            )

    async def _disconnect_peer(self, session_id: str, info: dict[str, Any]) -> None:
        current = self._peers.get(session_id)
        if current is info:
            self._peers.pop(session_id, None)
        writer = info.get('writer')
        if writer is None:
            return
        writer.close()
        with __import__('contextlib').suppress(ConnectionError, RuntimeError):
            await writer.wait_closed()

    async def _handle_deliver(self, frame: GatewayFrame) -> GatewayFrame:
        from .models import InboundMessage

        text = frame.text or ''
        semantic = None
        if frame.semantic:
            from .models import MessageSemantics

            with __import__('contextlib').suppress(ValueError):
                semantic = MessageSemantics(frame.semantic)
        inbound = InboundMessage(
            origin=frame.origin or '',
            text=text,
            message_id=frame.delivery_id or '',
            channel='',
            semantic=semantic,
        )
        try:
            ack = await self.gateway.receive(inbound)
        except Exception as exc:  # noqa: BLE001
            return GatewayFrame.nack(
                delivery_id=frame.delivery_id or frame.message_id, reason=f'deliver error: {exc}'
            )
        layer = ack.layer.value if hasattr(ack, 'layer') else 'accepted'
        return GatewayFrame.ack(
            delivery_id=frame.delivery_id or frame.message_id,
            layer=layer,
            message=ack.message if hasattr(ack, 'message') else '',
        )

    async def _handle_outbound(self, frame: GatewayFrame) -> GatewayFrame | None:
        """OUTBOUND (client→server): route a reply back to the IM channel.

        The origin encodes the channel + target (e.g.
        ``wechat:direct:{account}:{user}``); resolve them and call
        ``gateway.send`` so the OutboundDispatcher delivers to WeChat.
        """
        origin = frame.origin or ''
        text = frame.text or ''
        if not origin or not text:
            return GatewayFrame.nack(
                delivery_id=frame.message_id, reason='outbound requires origin+text'
            )
        channel, target = _resolve_origin(origin, self.gateway)
        if channel is None:
            return GatewayFrame.nack(
                delivery_id=frame.message_id, reason=f'unresolvable origin {origin!r}'
            )
        try:
            from .models import OutboundMessage

            result = await self.gateway.send(
                OutboundMessage(text=text, channel=channel, target=target, markdown=False)
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception('gateway ipc: OUTBOUND send failed origin=%s', origin[:24])
            return GatewayFrame.nack(delivery_id=frame.message_id, reason=f'send error: {exc}')
        if result is not None and getattr(result, 'ok', True) is False:
            error_category = getattr(result, 'error_category', '')
            category_value = getattr(error_category, 'value', '') or str(error_category or '')
            message = getattr(result, 'message', None) or category_value or 'send failed'
            logger.warning(
                'gateway ipc: OUTBOUND send rejected origin=%s channel=%s category=%s attempts=%s message=%s',
                origin[:24],
                channel,
                category_value,
                getattr(result, 'attempts', None),
                message,
            )
            return GatewayFrame.nack(
                delivery_id=frame.message_id,
                reason=f'send failed: {message}',
            )
        logger.info(
            'gateway ipc: OUTBOUND → send origin=%s channel=%s len=%d',
            origin[:24],
            channel,
            len(text),
        )
        return GatewayFrame.ack(delivery_id=frame.message_id, layer='processed', message='sent')

    async def _handle_event(self, frame: GatewayFrame) -> GatewayFrame | None:
        etype = frame.event_type or ''
        if etype == 'control.reload':
            name = (frame.payload or {}).get('channel', '')
            ok = self.gateway.reload_channel(name)
            return GatewayFrame.ack(
                delivery_id=frame.message_id,
                layer='accepted' if ok else 'nack',
                message=f'reload {name}: {"ok" if ok else "not found"}',
            )
        if etype == 'control.status':
            health = await self.gateway.health()
            health['bindings'] = _binding_snapshot(self.gateway)
            health['peers'] = self.peers_snapshot()
            # Echo the request message_id so the client's read loop can route
            # the reply back to the pending status() future.
            return GatewayFrame(
                type=FrameType.EVENT,
                message_id=frame.message_id,
                event_type='control.status',
                payload=health,
            )
        if etype == 'control.unbind':
            origin = str((frame.payload or {}).get('origin') or '')
            if not origin:
                return GatewayFrame.nack(
                    delivery_id=frame.message_id, reason='control.unbind requires origin'
                )
            removed = []
            if hasattr(self.gateway, 'binding'):
                terminate_matching = getattr(self.gateway.binding, 'terminate_matching', None)
                if callable(terminate_matching):
                    removed = terminate_matching(origin)
                else:
                    entry = self.gateway.binding.unbind(origin)
                    removed = [entry] if entry is not None else []
            await self._disconnect_matching_peers(origin)
            return GatewayFrame.ack(
                delivery_id=frame.message_id,
                layer='accepted',
                message=f'unbound {len(removed)} binding(s)',
            )
        return None


def _host_type(session_id: str, capabilities: list[str]) -> str:
    joined = ' '.join([session_id, *capabilities]).lower()
    if 'repl' in joined:
        return 'repl'
    if 'orchestrator' in joined or 'issue' in joined or 'run' in joined:
        return 'orchestrator'
    return 'opt_in'


def _binding_snapshot(gateway) -> list[dict[str, Any]]:
    binding = getattr(gateway, 'binding', None)
    all_bindings = getattr(binding, 'all_bindings', None)
    if not callable(all_bindings):
        return []
    return [
        {
            'origin': entry.origin,
            'session_id': entry.target.session_id,
            'host_type': entry.target.host_type,
            'connection_state': entry.connection_state,
        }
        for entry in all_bindings()
    ]


def _exclusive_origin_group(origin: str) -> str:
    parts = origin.split(':')
    if len(parts) >= 4 and parts[0] == 'wechat' and parts[1] == 'direct':
        return 'wechat:direct'
    return origin


def _same_exclusive_origin_group(left: str, right: str) -> bool:
    return _exclusive_origin_group(left) == _exclusive_origin_group(right)
