"""Channels service primitives (F-63 first iteration).

This package ships the cross-platform ``BaseChannel`` ABC, a thread-safe
``ChannelManager`` dispatcher, a minimal async HTTP transport with
webhook URL safety checks, and implementations for Feishu (飞书), Slack,
Discord, and WeChat (个人微信 via the iLink bot HTTP contract — see
``wechat_ilink``). MCP push channels remain deferred to a later
iteration. The Tool factory integration and configuration persistence
are also deferred.
"""

from __future__ import annotations

from .base import BaseChannel, ChannelManager
from .capabilities import (
    CapabilityDescriptor,
    CapabilityNotDeclaredError,
    ChannelAdapter,
    ChannelCapability,
    ChannelCapabilitySet,
    OutboundCapability,
)
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
from .feishu_app import FeishuAppChannelAdapter
from .models import ChannelConfig, ChannelMessage, ChannelType, MessageLevel
from .null_channel import NullChannel, RecordedSend
from .registry import ChannelAdapterRegistry, WebhookChannelAdapter, build_default_registry
from .results import (
    ChannelHealth,
    ChannelSendResult,
    CircuitState,
    ErrorCategory,
    SendStatus,
    ValidationResult,
)
from .retry import DEFAULT_RETRY_POLICY, RetryPolicy
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
from .wechat_ilink import (
    WeChatIlinkAuthStore,
    WeChatIlinkChannelAdapter,
    WeChatIlinkClient,
    WeChatPairingStore,
)

__all__ = [
    'DEFAULT_RETRY_POLICY',
    'DEFAULT_TIMEOUT_SECONDS',
    'BaseChannel',
    'CapabilityDescriptor',
    'CapabilityNotDeclaredError',
    'ChannelAdapter',
    'ChannelAdapterRegistry',
    'ChannelCapability',
    'ChannelCapabilitySet',
    'ChannelConfig',
    'ChannelDisabledError',
    'ChannelError',
    'ChannelHealth',
    'ChannelManager',
    'ChannelMessage',
    'ChannelNotFoundError',
    'ChannelSendResult',
    'ChannelTransport',
    'ChannelType',
    'CircuitState',
    'DiscordChannel',
    'ErrorCategory',
    'FEISHU_SUCCESS_CODE',
    'FeishuChannel',
    'FeishuAppChannelAdapter',
    'InvalidWebhookURLError',
    'MessageLevel',
    'NullChannel',
    'OutboundCapability',
    'RecordedSend',
    'RetryPolicy',
    'SendStatus',
    'SlackChannel',
    'TransportError',
    'TransportResponse',
    'UrllibChannelTransport',
    'ValidationResult',
    'WeChatIlinkAuthStore',
    'WeChatIlinkChannelAdapter',
    'WeChatIlinkClient',
    'WeChatPairingStore',
    'WebhookChannelAdapter',
    'build_default_registry',
    'WebhookSecretMissingError',
    'encode_json_body',
    'default_headers',
    'redact_webhook_url',
    'sign_feishu',
    'validate_webhook_url',
]
