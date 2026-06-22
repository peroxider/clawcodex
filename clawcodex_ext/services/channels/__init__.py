"""Channels service primitives (F-63 first iteration).

This package ships the cross-platform ``BaseChannel`` ABC, a thread-safe
``ChannelManager`` dispatcher, a minimal async HTTP transport with
webhook URL safety checks, and implementations for Feishu (飞书), Slack,
and Discord. The WeChat (企业微信) and MCP push channels are explicitly
deferred to later iterations. The Tool factory integration and
configuration persistence are also deferred.
"""

from __future__ import annotations

from .base import BaseChannel, ChannelManager
from .discord import DiscordChannel
from .exceptions import (
    ChannelDisabledError,
    ChannelError,
    ChannelNotFoundError,
    InvalidWebhookURLError,
    TransportError,
    WebhookSecretMissingError,
)
from .feishu import FEISHU_SUCCESS_CODE, FeishuChannel, sign_feishu
from .models import ChannelConfig, ChannelMessage, ChannelType, MessageLevel
from .null_channel import NullChannel, RecordedSend
from .slack import SlackChannel
from .transport import (
    DEFAULT_TIMEOUT_SECONDS,
    ChannelTransport,
    TransportResponse,
    UrllibChannelTransport,
    default_headers,
    encode_json_body,
    redact_webhook_url,
    validate_webhook_url,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "BaseChannel",
    "ChannelConfig",
    "ChannelDisabledError",
    "ChannelError",
    "ChannelManager",
    "ChannelMessage",
    "ChannelNotFoundError",
    "ChannelTransport",
    "ChannelType",
    "DiscordChannel",
    "FEISHU_SUCCESS_CODE",
    "FeishuChannel",
    "InvalidWebhookURLError",
    "MessageLevel",
    "NullChannel",
    "RecordedSend",
    "SlackChannel",
    "TransportError",
    "TransportResponse",
    "UrllibChannelTransport",
    "WebhookSecretMissingError",
    "encode_json_body",
    "default_headers",
    "redact_webhook_url",
    "sign_feishu",
    "validate_webhook_url",
]