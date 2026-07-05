"""Feishu App channel adapter tests.

The adapter is a thin shell over ``lark_oapi.channel.FeishuChannel``; tests
inject a fake channel implementing the small surface the adapter touches
(``connect_until_ready`` / ``disconnect`` / ``send`` / ``update_card`` /
``on`` / ``bot_identity``). SDK-internal wiring (WS loop, dispatcher, dedup
pipeline) is covered by the SDK's own tests and not re-tested here.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from lark_oapi.channel.errors import FeishuChannelErrorCode, SendError
from lark_oapi.channel.types import SendResult

from clawcodex_ext.services.channels.capabilities import ChannelCapability
from clawcodex_ext.services.channels.feishu_app import FeishuAppChannelAdapter
from clawcodex_ext.services.channels.models import ChannelConfig, ChannelMessage, ChannelType
from clawcodex_ext.services.channels.results import ErrorCategory, SendStatus


class _FakeChannel:
    def __init__(
        self,
        *,
        send_results: list | None = None,
        connect_exc: BaseException | None = None,
        bot_identity: Any | None = None,
    ) -> None:
        self.sent: list[dict] = []
        self.updated_cards: list[dict] = []
        self.connect_exc = connect_exc
        self.connected = False
        self.disconnected = False
        self._handlers: dict[str, Any] = {}
        self._bot_identity = bot_identity
        self._send_results = list(send_results or [])

    def on(self, name, handler=None) -> None:
        if isinstance(name, dict):
            self._handlers.update({k: v for k, v in name.items() if v is not None})
            return
        if handler is not None:
            self._handlers[name] = handler

    async def connect_until_ready(self, *, timeout: float | None = None) -> None:
        if self.connect_exc is not None:
            raise self.connect_exc
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def send(self, to, message, opts=None) -> SendResult:
        self.sent.append({'to': to, 'message': message})
        if self._send_results:
            result = self._send_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return SendResult.ok(message_id='om_sent')

    async def update_card(self, message_id: str, card: dict) -> SendResult:
        self.updated_cards.append({'message_id': message_id, 'card': card})
        return SendResult.ok(message_id=message_id)

    @property
    def bot_identity(self) -> Any:
        return self._bot_identity

    async def fire_message(self, inbound: Any) -> None:
        await self._handlers['message'](inbound)

    async def fire_card_action(self, payload: Any) -> None:
        await self._handlers['cardAction'](payload)

    async def fire_reconnecting(self) -> None:
        cb = self._handlers.get('reconnecting')
        if cb:
            res = cb()
            if inspect.isawaitable(res):
                await res

    async def fire_reconnected(self) -> None:
        cb = self._handlers.get('reconnected')
        if cb:
            res = cb()
            if inspect.isawaitable(res):
                await res


class _BlockingChannel(_FakeChannel):
    def __init__(self) -> None:
        super().__init__()
        self.release_connect = asyncio.Event()
        self.connect_entered = asyncio.Event()

    async def connect_until_ready(self, *, timeout: float | None = None) -> None:
        self.connect_entered.set()
        await self.release_connect.wait()
        self.connected = True


async def _sleep_forever() -> None:
    await asyncio.sleep(3600)


def _drain_test_loop(loop: asyncio.AbstractEventLoop, tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        task.cancel()
    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))


class _SdkLikeWsClient:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._auto_reconnect = True
        self._cache = SimpleNamespace(_cron=loop.create_task(_sleep_forever()))
        self.ping_task = loop.create_task(_sleep_forever())
        self.receive_task = loop.create_task(_sleep_forever())

    @property
    def tasks(self) -> list[asyncio.Task]:
        return [self._cache._cron, self.ping_task, self.receive_task]


class _SdkLikeChannel(_FakeChannel):
    def __init__(self, ws_client: _SdkLikeWsClient) -> None:
        super().__init__()
        self._ws_client = ws_client

    async def disconnect(self) -> None:
        await super().disconnect()
        self._ws_client = None


class _FakeFeishuSenderStore:
    def __init__(self) -> None:
        self.last_senders: dict[str, str] = {}

    def set_feishu_last_sender(self, channel_id: str, sender: str | None) -> None:
        if sender:
            self.last_senders[channel_id] = sender
        else:
            self.last_senders.pop(channel_id, None)

    def get_feishu_last_sender(self, channel_id: str) -> str | None:
        return self.last_senders.get(channel_id)


def _config(extra: dict | None = None) -> ChannelConfig:
    payload = {
        'connection_mode': 'websocket',
        'app_id': 'cli_app',
        'app_secret': 'secret',
        'allowed_user_open_id': 'ou_allowed',
        'bot_open_id': 'ou_bot',
        'batching': {'text_batch_delay_seconds': 0.01},
        'send': {'sdk_send_attempts': 1, 'sdk_send_timeout_seconds': 1.0},
    }
    if extra:
        payload.update(extra)
    return ChannelConfig(
        type=ChannelType.FEISHU,
        webhook_url='',
        name='feishu',
        extra=payload,
    )


def _sdk_inbound(
    *,
    message_id: str = 'om_msg_1',
    chat_id: str = 'oc_chat',
    chat_type: str = 'p2p',
    open_id: str = 'ou_allowed',
    text: str = 'hello',
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        content_text=text,
        create_time=123,
        raw_content_type='text',
        conversation=SimpleNamespace(chat_id=chat_id, chat_type=chat_type),
        sender=SimpleNamespace(open_id=open_id),
    )


def _card_action_event(
    *,
    approval_id: str,
    nonce: str,
    choice: str = 'y',
    operator_open_id: str = 'ou_allowed',
    chat_id: str = 'oc_chat',
    message_id: str = 'om_card',
) -> SimpleNamespace:
    return SimpleNamespace(
        message_id=message_id,
        chat_id=chat_id,
        operator=SimpleNamespace(open_id=operator_open_id),
        action=SimpleNamespace(
            tag='button',
            value={
                'clawcodex_action': 'permission_approval',
                'approval_id': approval_id,
                'nonce': nonce,
                'choice': choice,
            },
        ),
    )


def _send_error(code: FeishuChannelErrorCode, *, retryable: bool, hint: str = '') -> SendError:
    return SendError(code=code, retryable=retryable, hint=hint)


def test_feishu_app_adapter_declares_capabilities() -> None:
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: _FakeChannel())

    assert adapter.capabilities.has(ChannelCapability.OUTBOUND_TEXT)
    assert adapter.capabilities.has(ChannelCapability.INBOUND_POLLING)
    assert adapter.capabilities.has(ChannelCapability.CONTEXT_REPLY)
    assert adapter.capabilities.has(ChannelCapability.LOGIN_MANAGED)


@pytest.mark.asyncio
async def test_feishu_app_adapter_start_and_health_with_fake_channel() -> None:
    channel = _FakeChannel(bot_identity=SimpleNamespace(open_id='ou_bot', name='ClawCodex'))
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)

    await adapter.start()
    health = await adapter.health_check()

    assert channel.connected is True
    assert channel._handlers['message'] == adapter._on_message
    assert channel._handlers['cardAction'] == adapter._on_card_action
    assert health.healthy is True
    assert health.account_status == 'websocket:connected'
    assert health.extra['bot_open_id'] == 'ou_bot'


@pytest.mark.asyncio
async def test_feishu_app_adapter_start_blocks_until_channel_ready() -> None:
    channel = _BlockingChannel()
    adapter = FeishuAppChannelAdapter(
        _config({'websocket': {'startup_connect_timeout_seconds': 5}}),
        channel_factory=lambda s: channel,
    )

    start_task = asyncio.create_task(adapter.start())
    await asyncio.wait_for(channel.connect_entered.wait(), timeout=1.0)

    assert channel.connected is False
    assert start_task.done() is False

    channel.release_connect.set()
    await asyncio.wait_for(start_task, timeout=1.0)
    health = await adapter.health_check()

    assert health.account_status == 'websocket:connected'
    assert adapter._connect_task is None


@pytest.mark.asyncio
async def test_feishu_app_adapter_initial_retryable_failure_enters_background_retry() -> None:
    failing = _FakeChannel(connect_exc=RuntimeError('network down'))
    channels = [failing, _FakeChannel()]

    def factory(settings):
        return channels.pop(0)

    adapter = FeishuAppChannelAdapter(
        _config({'websocket': {'startup_connect_timeout_seconds': 0.1}}),
        channel_factory=factory,
    )

    await adapter.start()
    health = await adapter.health_check()

    assert health.healthy is False
    assert health.account_status == 'websocket:retrying'
    assert 'network down' in (health.last_error or '')
    assert adapter._connect_task is not None


@pytest.mark.asyncio
async def test_feishu_app_adapter_background_retry_recovers_to_connected() -> None:
    channels = [_FakeChannel(connect_exc=RuntimeError('network down')), _FakeChannel()]

    def factory(settings):
        return channels.pop(0)

    adapter = FeishuAppChannelAdapter(
        _config({'websocket': {'startup_connect_timeout_seconds': 0.1}}),
        channel_factory=factory,
        retry_sleep=lambda _seconds: asyncio.sleep(0),
    )

    await adapter.start()
    assert adapter._connect_task is not None

    await asyncio.wait_for(adapter._connect_task, timeout=1.0)
    health = await adapter.health_check()

    assert health.healthy is True
    assert health.account_status == 'websocket:connected'


@pytest.mark.asyncio
async def test_feishu_app_adapter_missing_credentials_do_not_retry() -> None:
    adapter = FeishuAppChannelAdapter(
        _config({'app_id': '', 'app_secret': ''}),
        channel_factory=lambda s: _FakeChannel(),
    )

    await adapter.start()
    health = await adapter.health_check()

    assert health.account_status == 'credentials_missing'
    assert adapter._connect_task is None


@pytest.mark.asyncio
async def test_feishu_app_adapter_stop_disconnects_channel() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    await adapter.stop()

    assert channel.disconnected is True
    health = await adapter.health_check()
    assert health.account_status == 'websocket:disconnected'


@pytest.mark.asyncio
async def test_feishu_app_adapter_stop_drains_sdk_ws_loop_tasks() -> None:
    sdk_loop = asyncio.new_event_loop()
    ws_client = _SdkLikeWsClient(sdk_loop)
    channel = _SdkLikeChannel(ws_client)
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    try:
        await adapter.stop()

        assert channel.disconnected is True
        assert ws_client._auto_reconnect is False
        assert all(task.done() for task in ws_client.tasks)
    finally:
        await asyncio.to_thread(_drain_test_loop, sdk_loop, ws_client.tasks)
        sdk_loop.close()


@pytest.mark.asyncio
async def test_feishu_adapter_inbound_translates_and_delivers() -> None:
    delivered = []
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    adapter.set_inbound_handler(delivered.append)
    await adapter.start()

    await channel.fire_message(_sdk_inbound())

    assert len(delivered) == 1
    assert delivered[0].text == 'hello'
    assert delivered[0].context_token == 'oc_chat'
    assert delivered[0].from_user_id == 'ou_allowed'


@pytest.mark.asyncio
async def test_feishu_adapter_inbound_drops_non_p2p() -> None:
    delivered = []
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    adapter.set_inbound_handler(delivered.append)
    await adapter.start()

    await channel.fire_message(_sdk_inbound(chat_type='group'))

    assert delivered == []


@pytest.mark.asyncio
async def test_feishu_adapter_tracks_last_known_sender_from_inbound_chat() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    await channel.fire_message(_sdk_inbound())

    assert adapter.last_known_sender() == 'oc_chat'


@pytest.mark.asyncio
async def test_feishu_adapter_last_sender_survives_restart_via_store() -> None:
    store = _FakeFeishuSenderStore()
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(
        _config(), channel_factory=lambda s: channel, sender_store=store
    )
    await adapter.start()

    await channel.fire_message(_sdk_inbound(message_id='om_persisted'))

    restarted = FeishuAppChannelAdapter(
        _config(), channel_factory=lambda s: _FakeChannel(), sender_store=store
    )

    assert adapter.last_known_sender() == 'oc_chat'
    assert restarted.last_known_sender() == 'oc_chat'


@pytest.mark.asyncio
async def test_feishu_send_uses_context_token_chat_id() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    result = await adapter.send(ChannelMessage(text='hello'), context_token='oc_chat')

    assert result.ok is True
    assert result.provider_receipt == 'om_sent'
    assert channel.sent == [{'to': 'oc_chat', 'message': {'text': 'hello'}}]


@pytest.mark.asyncio
async def test_feishu_send_prefers_context_chat_id_when_target_is_origin_open_id() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    result = await adapter.send(
        ChannelMessage(text='hello', metadata={'origin': 'feishu:dm:cli_app:ou_allowed'}),
        target='ou_allowed',
        context_token='oc_chat',
    )

    assert result.ok is True
    assert channel.sent[0]['to'] == 'oc_chat'


@pytest.mark.asyncio
async def test_feishu_send_returns_retryable_on_rate_limit() -> None:
    channel = _FakeChannel(
        send_results=[
            SendResult.fail(
                _send_error(
                    FeishuChannelErrorCode.RATE_LIMITED, retryable=True, hint='rate limited'
                )
            )
        ]
    )
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    result = await adapter.send(ChannelMessage(text='hello'), target='oc_chat')

    assert result.ok is False
    assert result.status is SendStatus.RETRYABLE_ERROR
    assert result.error_category is ErrorCategory.RATE_LIMIT
    assert result.retryable is True


@pytest.mark.asyncio
async def test_feishu_send_returns_nonretryable_on_bad_request() -> None:
    channel = _FakeChannel(
        send_results=[
            SendResult.fail(
                _send_error(
                    FeishuChannelErrorCode.FORMAT_ERROR, retryable=False, hint='bad payload'
                )
            )
        ]
    )
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    result = await adapter.send(ChannelMessage(text='hello'), target='oc_chat')

    assert result.ok is False
    assert result.status is SendStatus.NONRETRYABLE_ERROR
    assert result.error_category is ErrorCategory.CLIENT_ERROR


@pytest.mark.asyncio
async def test_feishu_send_falls_back_to_text_on_format_error() -> None:
    channel = _FakeChannel(
        send_results=[
            SendResult.fail(
                _send_error(
                    FeishuChannelErrorCode.FORMAT_ERROR, retryable=False, hint='post rejected'
                )
            ),
            SendResult.ok(message_id='om_sent'),
        ]
    )
    cfg = _config({'send': {'sdk_send_attempts': 1, 'sdk_send_timeout_seconds': 1.0}})
    adapter = FeishuAppChannelAdapter(cfg, channel_factory=lambda s: channel)
    await adapter.start()

    result = await adapter.send(
        ChannelMessage(text='```code\nx\n```', markdown=True), target='oc_chat'
    )

    assert result.ok is True
    assert channel.sent[0]['message'] == {'markdown': '```code\nx\n```'}
    assert channel.sent[1]['message'] == {'text': '```code\nx\n```'}


@pytest.mark.asyncio
async def test_feishu_permission_metadata_sends_interactive_card() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()
    message = ChannelMessage(
        text='fallback',
        metadata={
            'intent': 'permission_approval',
            'permission': {
                'message': 'ClawCodex wants to use Bash.',
                'suggestion': 'Review command',
                'options': [
                    {'value': 'y', 'label': '允许'},
                    {'value': 'n', 'label': '拒绝'},
                ],
                'expires_in_seconds': 600,
            },
        },
    )

    result = await adapter.send(message, context_token='oc_chat')

    assert result.ok is True
    card = channel.sent[0]['message']['card']
    assert card['header']['title']['content'] == '权限审批'


@pytest.mark.asyncio
async def test_feishu_card_click_emits_approval_inbound_and_updates_card() -> None:
    channel = _FakeChannel()
    delivered = []
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    adapter.set_inbound_handler(delivered.append)
    await adapter.start()
    message = ChannelMessage(
        text='fallback',
        metadata={
            'intent': 'permission_approval',
            'permission': {
                'message': 'ClawCodex wants to use Bash.',
                'options': [{'value': 'y', 'label': '允许'}],
            },
        },
    )
    await adapter.send(message, context_token='oc_chat')
    pending = next(iter(adapter.approval_manager.pending.values()))

    await channel.fire_card_action(
        _card_action_event(approval_id=pending.approval_id, nonce=pending.nonce, choice='y')
    )

    assert len(delivered) == 1
    assert delivered[0].text == 'y'
    assert delivered[0].semantic_tags == ['approval']
    assert len(channel.updated_cards) == 1
    resolved = channel.updated_cards[0]['card']
    assert resolved['header']['template'] == 'green'
    assert all(element.get('tag') != 'action' for element in resolved['elements'])


@pytest.mark.asyncio
async def test_feishu_card_click_invalid_payload_does_nothing() -> None:
    channel = _FakeChannel()
    delivered = []
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    adapter.set_inbound_handler(delivered.append)
    await adapter.start()

    await channel.fire_card_action(_card_action_event(approval_id='unknown', nonce='x'))

    assert delivered == []
    assert channel.updated_cards == []


@pytest.mark.asyncio
async def test_feishu_send_does_not_hang_forever_when_sdk_hangs() -> None:
    class _HangingChannel(_FakeChannel):
        def __init__(self) -> None:
            super().__init__()
            self.send_started = asyncio.Event()

        async def send(self, to, message, opts=None) -> SendResult:
            self.send_started.set()
            await asyncio.Event().wait()  # never returns
            return SendResult.ok()  # pragma: no cover

    channel = _HangingChannel()
    cfg = _config({'send': {'sdk_send_attempts': 1, 'sdk_send_timeout_seconds': 0.5}})
    adapter = FeishuAppChannelAdapter(cfg, channel_factory=lambda s: channel)
    await adapter.start()

    task = asyncio.create_task(adapter.send(ChannelMessage(text='first'), target='oc_chat'))
    await asyncio.wait_for(channel.send_started.wait(), timeout=1.0)

    try:
        result = await asyncio.wait_for(task, timeout=3.0)
    except asyncio.TimeoutError:
        pytest.fail('adapter.send hung forever when channel.send never returned')

    assert result.ok is False
    assert result.error_category is ErrorCategory.TIMEOUT


@pytest.mark.asyncio
async def test_feishu_health_reflects_reconnecting_reconnected_hooks() -> None:
    channel = _FakeChannel()
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda s: channel)
    await adapter.start()

    await channel.fire_reconnecting()
    assert (await adapter.health_check()).account_status == 'websocket:reconnecting'

    await channel.fire_reconnected()
    health = await adapter.health_check()
    assert health.account_status == 'websocket:connected'
    assert health.healthy is True
