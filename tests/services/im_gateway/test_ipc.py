"""Tests for the GatewayIpcServer / GatewayIpcClient (P4 IPC)."""

from __future__ import annotations

import asyncio

import pytest

from clawcodex_ext.services.im_gateway.binding import BindingPolicy
from clawcodex_ext.services.im_gateway.ipc_client import GatewayIpcClient
from clawcodex_ext.services.im_gateway.ipc_protocol import FrameType, GatewayFrame
from clawcodex_ext.services.im_gateway.ipc_server import GatewayIpcServer
from clawcodex_ext.services.im_gateway.models import (
    WECHAT_DIRECT_ALL_ORIGIN,
    AckLayer,
    AckReceipt,
)


class _FakeGateway:
    def __init__(self):
        self.received = []
        self.reloaded = []
        self.sent = []  # outbound messages from OUTBOUND frames
        self.binding = BindingPolicy()

    async def receive(self, message):
        self.received.append(message)
        return AckReceipt(message.message_id or 'd1', AckLayer.ENQUEUED, 'enqueued')

    def reload_channel(self, name):
        self.reloaded.append(name)
        return name != 'missing'

    async def health(self):
        return {'running': True, 'channels': ['wechat'], 'peers': 0}

    async def send(self, message):
        """OutboundDispatcher stand-in: records OUTBOUND-driven sends."""
        self.sent.append(message)
        from clawcodex_ext.services.channels.results import ChannelSendResult

        return ChannelSendResult.success(getattr(message, 'channel', 'wechat'))


@pytest.mark.asyncio
async def test_ipc_register_and_heartbeat_ack(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            resp = await client.register(
                session_id='repl_main', origin='o1', capabilities=['outbound_text']
            )
            assert resp is not None and resp.ack_layer == 'accepted'
            bound = gw.binding.get('o1')
            assert bound is not None
            assert bound.target.session_id == 'repl_main'
            hb = await client.heartbeat()
            assert hb is not None and hb.ack_layer == 'accepted'
        await asyncio.sleep(0.05)  # let server process EOF
        assert server.connected_count == 0  # client closed → peer removed
        assert gw.binding.get('o1').connection_state == 'offline'
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_heartbeat_after_unregister_does_not_crash_handler(tmp_path) -> None:
    """A stale in-connection session must not crash after the peer entry is removed."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    reader = None
    writer = None
    try:
        reader, writer = await asyncio.open_unix_connection(str(tmp_path / 'gw.sock'))

        writer.write(GatewayFrame.register(session_id='orchestrator-1130', origin='o1').encode())
        await writer.drain()
        registered = GatewayFrame.decode(await reader.readline())
        assert registered.ack_layer == 'accepted'

        writer.write(
            GatewayFrame(type=FrameType.UNREGISTER, session_id='orchestrator-1130').encode()
        )
        await writer.drain()
        unregistered = GatewayFrame.decode(await reader.readline())
        assert unregistered.ack_layer == 'accepted'

        writer.write(GatewayFrame.heartbeat(session_id='orchestrator-1130').encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=1.0)
        assert raw, 'server closed the connection instead of handling the stale session'
        heartbeat = GatewayFrame.decode(raw)
        assert heartbeat.ack_layer == 'accepted'
    finally:
        if writer is not None:
            writer.close()
            with __import__('contextlib').suppress(ConnectionError, RuntimeError):
                await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_ipc_same_session_reconnect_keeps_replacement_online(tmp_path) -> None:
    """Closing an older connection must not remove a newer peer with the same session id."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    old_writer = None
    new_writer = None
    try:
        old_reader, old_writer = await asyncio.open_unix_connection(str(tmp_path / 'gw.sock'))
        old_writer.write(
            GatewayFrame.register(session_id='orchestrator-1130', origin='o1').encode()
        )
        await old_writer.drain()
        old_registered = GatewayFrame.decode(await old_reader.readline())
        assert old_registered.ack_layer == 'accepted'

        new_reader, new_writer = await asyncio.open_unix_connection(str(tmp_path / 'gw.sock'))
        new_writer.write(
            GatewayFrame.register(session_id='orchestrator-1130', origin='o1').encode()
        )
        await new_writer.drain()
        new_registered = GatewayFrame.decode(await new_reader.readline())
        assert new_registered.ack_layer == 'accepted'

        old_writer.close()
        with __import__('contextlib').suppress(ConnectionError, RuntimeError):
            await old_writer.wait_closed()
        await asyncio.sleep(0.05)

        assert server.is_online('orchestrator-1130') is True
        assert gw.binding.get('o1').connection_state == 'active'

        new_writer.write(GatewayFrame.heartbeat(session_id='orchestrator-1130').encode())
        await new_writer.drain()
        raw = await asyncio.wait_for(new_reader.readline(), timeout=1.0)
        assert raw, 'replacement connection was closed by stale session cleanup'
        heartbeat = GatewayFrame.decode(raw)
        assert heartbeat.ack_layer == 'accepted'
    finally:
        for writer in (old_writer, new_writer):
            if writer is not None:
                writer.close()
                with __import__('contextlib').suppress(ConnectionError, RuntimeError):
                    await writer.wait_closed()
        await server.close()


@pytest.mark.asyncio
async def test_ipc_wechat_channel_binding_is_single_runtime_and_disconnects_previous(
    tmp_path,
) -> None:
    """A WeChat channel can be bound to REPL or orchestrator, never both."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    repl = GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl-main')
    orchestrator = GatewayIpcClient(tmp_path / 'gw.sock', instance_id='orchestrator-main')
    try:
        await repl.connect()
        await repl.register(
            session_id='repl-main',
            origin=WECHAT_DIRECT_ALL_ORIGIN,
            capabilities=['outbound_text'],
        )
        assert gw.binding.get('wechat:direct:acct:user').target.session_id == 'repl-main'

        await orchestrator.connect()
        await orchestrator.register(
            session_id='orchestrator-main',
            origin=WECHAT_DIRECT_ALL_ORIGIN,
            capabilities=['outbound_text', 'orchestrator'],
        )
        await asyncio.sleep(0.1)

        entry = gw.binding.get('wechat:direct:acct:user')
        assert entry is not None
        assert entry.target.session_id == 'orchestrator-main'
        assert entry.target.host_type == 'orchestrator'
        assert entry.connection_state == 'active'
        assert server.is_online('repl-main') is False
        assert server.is_online('orchestrator-main') is True

        # The previous REPL closing later must not mark the new orchestrator
        # binding offline.
        await repl.close()
        await asyncio.sleep(0.05)
        assert gw.binding.get('wechat:direct:acct:user').connection_state == 'active'
    finally:
        await repl.close()
        await orchestrator.close()
        await server.close()


@pytest.mark.asyncio
async def test_ipc_resolve_wildcard_origin_uses_adapter_context_token(tmp_path) -> None:
    """A wildcard OUTBOUND origin resolves to a concrete sender via the
    WeChat adapter's ``last_known_sender`` — which returns the most recent
    real inbound sender, else a persisted context-token user (survives a
    gateway restart with no new inbound). This is what lets an orchestrator
    emit startup events to an operator who last messaged in a previous
    gateway lifetime."""
    from clawcodex_ext.services.channels.models import ChannelType
    from clawcodex_ext.services.im_gateway.ipc_server import _resolve_origin

    class _Cfg:
        type = ChannelType.WECHAT

    class _Adapter:
        _config = _Cfg()
        channel_id = 'wechat'
        _account_id = 'acct@im.bot'

        def last_known_sender(self):
            return 'user@im.wechat'

    class _Registry:
        def all_adapters(self):
            return [_Adapter()]

    class _Gateway:
        registry = _Registry()

    channel, target = _resolve_origin(WECHAT_DIRECT_ALL_ORIGIN, _Gateway())
    assert channel == 'wechat'
    assert target == 'user@im.wechat'


@pytest.mark.asyncio
async def test_ipc_resolve_wildcard_origin_nacks_when_no_sender_known(tmp_path) -> None:
    """If the WeChat adapter knows no sender (no recent inbound, no persisted
    context token), the wildcard cannot be resolved — the caller NACKs
    instead of silently treating ``*`` as a real recipient."""
    from clawcodex_ext.services.im_gateway.ipc_server import _resolve_origin

    class _Gateway:
        registry = None

    channel, target = _resolve_origin(WECHAT_DIRECT_ALL_ORIGIN, _Gateway())
    assert channel is None and target is None


@pytest.mark.asyncio
async def test_ipc_wildcard_outbound_delivers_via_real_adapter_context_token(tmp_path) -> None:
    """End-to-end: a wildcard OUTBOUND frame on a real gateway with a real
    WeChat adapter (fake transport) is delivered to the operator whose
    context token was persisted in a previous lifetime — no new inbound
    needed. This is the orchestrator-startup-notification path."""
    from clawcodex_ext.services.im_gateway.config import GatewayConfig
    from clawcodex_ext.services.im_gateway.gateway import MessageGateway
    from clawcodex_ext.services.im_gateway.ipc_server import _resolve_origin

    # Build a real adapter with a fake transport and seed a persisted
    # context token for a known sender (as a prior inbound would have).
    from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType
    from clawcodex_ext.services.channels.transport import ChannelTransport, TransportResponse
    from clawcodex_ext.services.channels.wechat_ilink import (
        WeChatAuthRecord,
        WeChatIlinkAuthStore,
        WeChatIlinkChannelAdapter,
    )
    from clawcodex_ext.services.im_gateway.config import ReliabilityConfig
    from clawcodex_ext.services.im_gateway.store import ReliabilityStore

    class _FakeTransport(ChannelTransport):
        def __init__(self):
            self.sent: list[dict] = []

        async def post(self, url, body, *, headers=None, timeout=10.0):  # type: ignore[override]
            import json as _json
            import urllib.parse as _up

            path = _up.urlparse(url).path
            payload = _json.loads(body.decode('utf-8')) if body else {}
            if path in {'/sendmessage', '/ilink/bot/sendmessage'}:
                msg = payload.get('msg') if isinstance(payload.get('msg'), dict) else payload
                self.sent.append(msg)
                return TransportResponse(200, _json.dumps({'message_id': 'srv_1'}).encode(), {})
            return TransportResponse(200, b'{}', {})

    state_dir = tmp_path / 'state'
    store = ReliabilityStore(state_dir, ReliabilityConfig())
    store.set_context_token('default', 'operator@im.wechat', 'ctx_tok')

    cfg = ChannelConfig(
        type=ChannelType.WECHAT,
        webhook_url='https://ilinkai.weixin.qq.com/dummy',
        name='wechat',
        enabled=True,
        extra={'base_url': 'https://ilinkai.weixin.qq.com', 'account_id': 'default'},
    )
    transport = _FakeTransport()
    adapter = WeChatIlinkChannelAdapter(
        cfg,
        auth_store=WeChatIlinkAuthStore(state_dir / 'auth.json'),
        store=store,
        transport=transport,
        max_consecutive_failures=10,
    )
    adapter._auth_store.save(
        WeChatAuthRecord(
            bot_token='bot_tok',
            account_id='default',
            base_url='https://ilinkai.weixin.qq.com',
            user_id='bot_user',
        )
    )
    adapter.load_credentials()

    gw = MessageGateway(GatewayConfig(state_dir=str(state_dir)))
    gw.registry.register(adapter)

    # No inbound in this gateway lifetime → in-memory map empty. The
    # wildcard must still resolve via the persisted context token.
    channel, target = _resolve_origin(WECHAT_DIRECT_ALL_ORIGIN, gw)
    assert channel == 'wechat'
    assert target == 'operator@im.wechat'

    # And a real OUTBOUND dispatch delivers to that target.
    from clawcodex_ext.services.im_gateway.models import OutboundMessage

    await gw.send(OutboundMessage(text='hi', channel='wechat', target=target, markdown=False))
    assert transport.sent, 'WeChat sendmessage was not called'
    assert transport.sent[0]['to_user_id'] == 'operator@im.wechat'


@pytest.mark.asyncio
async def test_ipc_deliver_returns_enqueued_ack(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            await client.register(session_id='repl_main', origin='o1')
            resp = await client.deliver(
                delivery_id='d1', session_id='repl_main', origin='o1', text='hello'
            )
            assert resp is not None
            assert resp.ack_layer == 'enqueued'
        assert len(gw.received) == 1
        assert gw.received[0].text == 'hello'
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_deliver_dedupes_by_delivery_id(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            await client.register(session_id='repl_main', origin='o')
            r1 = await client.deliver(delivery_id='d1', session_id='s', origin='o', text='a')
            r2 = await client.deliver(delivery_id='d1', session_id='s', origin='o', text='a')
            assert r1 is not None and r1.ack_layer == 'enqueued'
            assert r2 is None  # deduped client-side
        assert len(gw.received) == 1
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_deliver_requires_register(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            resp = await client.deliver(delivery_id='d1', session_id='s', origin='o', text='a')
            assert resp is not None
            assert resp.type.value == 'nack'
            assert 'not registered' in (resp.reason or '')
        assert gw.received == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_client_allows_retry_when_no_ack(monkeypatch, tmp_path) -> None:
    client = GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main')
    sent: list[GatewayFrame] = []

    async def _no_ack(frame: GatewayFrame) -> GatewayFrame | None:
        sent.append(frame)
        return None

    monkeypatch.setattr(client, '_send', _no_ack)
    assert await client.deliver(delivery_id='d1', session_id='s', origin='o', text='a') is None
    assert await client.deliver(delivery_id='d1', session_id='s', origin='o', text='a') is None
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_ipc_control_reload_live(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='ctrl') as client:
            resp = await client.reload_channel('wechat')
            assert resp is not None and resp.ack_layer == 'accepted'
            missing = await client.reload_channel('missing')
            assert missing is not None and missing.ack_layer == 'nack'
        assert gw.reloaded == ['wechat', 'missing']
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_control_status(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='ctrl') as client:
            health = await client.status()
            assert health is not None
            assert health['channels'] == ['wechat']
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_status_and_unbind_report_and_remove_wechat_conversation(
    tmp_path,
) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    repl = GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl-main')
    try:
        await repl.connect()
        await repl.register(
            session_id='repl-main',
            origin=WECHAT_DIRECT_ALL_ORIGIN,
            capabilities=['outbound_text'],
        )
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='ctrl') as ctrl:
            health = await ctrl.status()
            assert health is not None
            assert health['bindings'] == [
                {
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'session_id': 'repl-main',
                    'host_type': 'repl',
                    'connection_state': 'active',
                }
            ]
            assert health['peers'] == [
                {
                    'session_id': 'repl-main',
                    'origin': WECHAT_DIRECT_ALL_ORIGIN,
                    'host_type': 'repl',
                    'online': True,
                }
            ]

            resp = await ctrl.unbind_origin(WECHAT_DIRECT_ALL_ORIGIN)
            assert resp is not None and resp.ack_layer == 'accepted'
        await asyncio.sleep(0.1)
        assert gw.binding.get('wechat:direct:acct:user') is None
        assert server.is_online('repl-main') is False
    finally:
        await repl.close()
        await server.close()


@pytest.mark.asyncio
async def test_ipc_peer_online_after_register_then_offline(tmp_path) -> None:
    clock = [1000.0]
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw, clock=lambda: clock[0])
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            await client.register(session_id='repl_main', origin='o1')
            assert server.is_online('repl_main') is True
            clock[0] = 1000.0 + 120  # beyond heartbeat timeout
            assert server.is_online('repl_main') is False
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_server_pushes_deliver_to_registered_client(tmp_path) -> None:
    """server.push_deliver writes a DELIVER frame the client receives via on_deliver."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    delivered: list[GatewayFrame] = []
    try:
        async with GatewayIpcClient(
            tmp_path / 'gw.sock',
            instance_id='repl_main',
            on_deliver=lambda f: asyncio.ensure_future(_append(f)),
        ) as client:

            async def _append(f):
                delivered.append(f)

            await client.register(session_id='repl_main', origin='wechat:direct:acct:user_zhao')
            # server pushes an inbound message to that origin
            await server.push_deliver(
                origin='wechat:direct:acct:user_zhao',
                delivery_id='d1',
                text='hello from wechat',
                semantic='newPrompt',
            )
            await asyncio.sleep(0.1)  # let the read loop dispatch
        assert len(delivered) == 1
        assert delivered[0].type.value == 'deliver'
        assert delivered[0].text == 'hello from wechat'
        assert delivered[0].origin == 'wechat:direct:acct:user_zhao'
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_push_deliver_noop_when_origin_not_registered(tmp_path) -> None:
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        # no client registered for this origin — push must not raise
        await server.push_deliver(origin='wechat:direct:acct:nobody', delivery_id='d1', text='x')
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_client_send_outbound_calls_gateway_send(tmp_path) -> None:
    """OUTBOUND frame (client→server) routes to gateway.send → WeChat."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            await client.register(session_id='repl_main', origin='wechat:direct:acct:user_zhao')
            await client.send_outbound(
                origin='wechat:direct:acct:user_zhao', text='reply from agent'
            )
        await asyncio.sleep(0.05)
        assert len(gw.sent) == 1
        assert gw.sent[0].text == 'reply from agent'
        assert gw.sent[0].channel == 'wechat'
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_client_send_outbound_returns_nack_when_gateway_send_fails(tmp_path) -> None:
    """A failed gateway.send result must be visible to the IPC client."""
    from clawcodex_ext.services.channels.results import ChannelSendResult, ErrorCategory

    gw = _FakeGateway()

    async def _rate_limited_send(message):
        gw.sent.append(message)
        return ChannelSendResult.retryable_error(
            'wechat',
            message='rate limited',
            category=ErrorCategory.RATE_LIMIT,
            attempts=5,
        )

    gw.send = _rate_limited_send
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='repl_main') as client:
            await client.register(session_id='repl_main', origin='wechat:direct:acct:user_zhao')
            response = await client.send_outbound(
                origin='wechat:direct:acct:user_zhao', text='reply from agent'
            )

        assert response is not None
        assert response.type is FrameType.NACK
        assert 'rate limited' in (response.reason or '')
        assert len(gw.sent) == 1
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_client_send_outbound_returns_nack_for_unresolvable_origin(tmp_path) -> None:
    """OUTBOUND NACKs are observable by the client."""
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='orch') as client:
            response = await client.send_outbound(origin='slack:dm:T123:U456', text='reply')

        assert response is not None
        assert response.type is FrameType.NACK
        assert 'unresolvable origin' in (response.reason or '')
        assert gw.sent == []
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_ipc_client_send_returns_none_on_broken_pipe(tmp_path) -> None:
    """_send must catch ConnectionError (gateway stopped) and return None.

    The gateway and orchestrator are decoupled — either may be stopped
    independently. When the gateway socket is gone, _send must not
    propagate BrokenPipeError; it returns None so the caller can
    reconnect gracefully without a traceback.
    """
    gw = _FakeGateway()
    server = GatewayIpcServer(tmp_path / 'gw.sock', gw)
    await server.start()
    try:
        async with GatewayIpcClient(tmp_path / 'gw.sock', instance_id='orch') as client:
            await client.register(session_id='orch', origin='wechat:direct:*:*')
            # Simulate gateway gone: close the server socket so the client's
            # writer.drain() raises BrokenPipeError on the next send.
            await server.close()
            await asyncio.sleep(0.05)  # let the OS propagate the closed socket

            # heartbeat must return None, not raise BrokenPipeError.
            response = await client.heartbeat()
            assert response is None
    finally:
        await server.close()
