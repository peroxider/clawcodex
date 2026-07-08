"""Feishu registry mode dispatch tests."""

from __future__ import annotations

import pytest

from clawcodex_ext.services.channels.feishu_app import FeishuAppChannelAdapter
from clawcodex_ext.services.channels.models import ChannelConfig, ChannelType
from clawcodex_ext.services.channels.registry import WebhookChannelAdapter, build_default_registry


def test_feishu_registry_uses_webhook_when_legacy_webhook_url_present() -> None:
    cfg = ChannelConfig(
        type=ChannelType.FEISHU,
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/abcdef",
        name="feishu",
    )

    adapter = build_default_registry().create(cfg)

    assert isinstance(adapter, WebhookChannelAdapter)


def test_feishu_registry_uses_app_adapter_for_websocket_mode() -> None:
    cfg = ChannelConfig(
        type=ChannelType.FEISHU,
        webhook_url="",
        name="feishu",
        extra={
            "connection_mode": "websocket",
            "app_id": "cli_app",
            "app_secret": "secret",
            "allowed_user_open_id": "ou_allowed",
        },
    )

    adapter = build_default_registry().create(cfg)

    assert isinstance(adapter, FeishuAppChannelAdapter)


def test_feishu_registry_rejects_unknown_mode() -> None:
    cfg = ChannelConfig(
        type=ChannelType.FEISHU,
        webhook_url="",
        name="feishu",
        extra={"connection_mode": "sideways"},
    )

    with pytest.raises(ValueError, match="connection_mode"):
        build_default_registry().create(cfg)
