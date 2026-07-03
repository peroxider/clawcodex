from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from clawcodex_ext.services.channels.feishu_app import FeishuAppChannelAdapter
from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType


class _FakeChannel:
    def __init__(self) -> None:
        self.updated_cards: list[dict] = []

    async def update_card(self, message_id: str, card: dict) -> None:
        self.updated_cards.append({'message_id': message_id, 'card': card})


def _config() -> ChannelConfig:
    return ChannelConfig(
        type=ChannelType.FEISHU,
        webhook_url='',
        name='feishu',
        extra={
            'connection_mode': 'websocket',
            'app_id': 'cli_app',
            'app_secret': 'secret',
            'allowed_user_open_id': 'ou_allowed',
        },
    )


def _card_action_event(*, approval_id: str, nonce: str) -> SimpleNamespace:
    return SimpleNamespace(
        message_id='om_card',
        chat_id='oc_chat',
        operator=SimpleNamespace(open_id='ou_allowed'),
        action=SimpleNamespace(
            tag='button',
            value={
                'clawcodex_action': 'permission_approval',
                'approval_id': approval_id,
                'nonce': nonce,
                'choice': 'y',
            },
        ),
    )


@pytest.mark.asyncio
async def test_feishu_card_click_updates_card_before_slow_gateway_handler() -> None:
    channel = _FakeChannel()
    started = asyncio.Event()
    release = asyncio.Event()
    delivered = []
    adapter = FeishuAppChannelAdapter(_config(), channel_factory=lambda _settings: channel)
    adapter._channel = channel
    adapter._main_loop = asyncio.get_running_loop()

    async def _slow_handler(message) -> None:
        delivered.append(message)
        started.set()
        await release.wait()

    adapter.set_inbound_handler(_slow_handler)
    pending = adapter.approval_manager.create_pending(
        origin='feishu:dm:cli_app:ou_allowed',
        chat_id='oc_chat',
        allowed_user_open_id='ou_allowed',
        choices={'y'},
        ttl_seconds=60,
    )

    task = asyncio.create_task(
        adapter._on_card_action(
            _card_action_event(approval_id=pending.approval_id, nonce=pending.nonce)
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    try:
        assert channel.updated_cards, 'card should be resolved before gateway delivery finishes'
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert len(delivered) == 1
