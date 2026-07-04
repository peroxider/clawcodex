"""Channel adapter capability model and contracts.

This is the P1 contract layer: every channel (WeChat + the legacy
Feishu/Slack/Discord webhook channels) is a :class:`ChannelAdapter`
that declares a :class:`ChannelCapabilitySet`. The gateway calls an
adapter only through capability protocols (``OutboundCapability``,
``InboundCapability``, …) and must ``require_capability`` first —
undeclared capabilities fail closed.

The legacy webhook channels do not implement this ABC directly; they
are wrapped by :class:`WebhookChannelAdapter` (see ``registry.py``)
which adapts :class:`BaseChannel` to the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from .models import ChannelMessage
from .results import ChannelHealth, ChannelSendResult, ValidationResult
from .retry import DEFAULT_RETRY_POLICY, RetryPolicy


class ChannelCapability(str, Enum):
    """Capability tags an adapter may declare."""

    OUTBOUND_TEXT = "outbound_text"
    INBOUND_POLLING = "inbound_polling"
    INBOUND_WEBHOOK = "inbound_webhook"  # reserved contract, not implemented in v1
    CONTEXT_REPLY = "context_reply"
    LOGIN_MANAGED = "login_managed"
    MEDIA_IMAGE = "media_image"
    MEDIA_FILE = "media_file"
    MEDIA_VIDEO = "media_video"


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Limits / metadata for a declared capability.

    ``supports_markdown=False`` tells the ``OutboundDispatcher`` to strip
    Markdown to plain text before sending (WeChat iLink). ``max_text_length``
    drives long-message splitting / LiveView fallback.
    """

    capability: ChannelCapability
    supports_markdown: bool = False
    max_text_length: int | None = None
    requires_login: bool = False
    media_max_size_bytes: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelCapabilitySet:
    """Immutable set of declared capabilities + their descriptors."""

    capabilities: frozenset[ChannelCapability]
    descriptors: dict[ChannelCapability, CapabilityDescriptor] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for cap in self.descriptors:
            if cap not in self.capabilities:
                raise ValueError(f"descriptor for {cap!r} but capability not declared")

    def has(self, capability: ChannelCapability) -> bool:
        return capability in self.capabilities

    def descriptor(self, capability: ChannelCapability) -> CapabilityDescriptor | None:
        return self.descriptors.get(capability)

    @classmethod
    def of(
        cls,
        *capabilities: ChannelCapability,
        descriptors: dict[ChannelCapability, CapabilityDescriptor] | None = None,
    ) -> ChannelCapabilitySet:
        caps = frozenset(capabilities)
        desc = dict(descriptors or {})
        return cls(capabilities=caps, descriptors=desc)


class CapabilityNotDeclaredError(Exception):
    """Raised when a caller invokes a capability the adapter did not declare."""


@runtime_checkable
class OutboundCapability(Protocol):
    """Adapter declaring ``outbound_text`` must implement this."""

    channel_id: str

    async def send(
        self,
        message: ChannelMessage,
        *,
        target: str | None = None,
        context_token: str | None = None,
    ) -> ChannelSendResult: ...


@runtime_checkable
class InboundCapability(Protocol):
    """Adapter declaring ``inbound_polling`` must implement this."""

    channel_id: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class ContextReplyCapability(Protocol):
    """Adapter declaring ``context_reply`` must carry a context token on replies."""

    channel_id: str


@runtime_checkable
class LoginManagedCapability(Protocol):
    """Adapter declaring ``login_managed`` owns a login/session lifecycle."""

    channel_id: str


class ChannelAdapter(ABC):
    """Physical implementation boundary for a channel.

    Subclasses declare ``capabilities`` and implement the corresponding
    capability protocols. The base contract covers config validation,
    health check, and retry policy.
    """

    @property
    @abstractmethod
    def channel_id(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ChannelCapabilitySet: ...

    @property
    def retry_policy(self) -> RetryPolicy:
        return DEFAULT_RETRY_POLICY

    @abstractmethod
    def validate_config(self) -> ValidationResult: ...

    @abstractmethod
    async def health_check(self) -> ChannelHealth: ...

    def require_capability(self, capability: ChannelCapability) -> None:
        """Fail closed if ``capability`` is not declared."""
        if not self.capabilities.has(capability):
            raise CapabilityNotDeclaredError(
                f"channel {self.channel_id!r} does not declare {capability.value!r}"
            )

    def set_inbound_handler(self, handler: Callable[..., Any]) -> None:
        """Hook for adapters declaring ``inbound_polling``. No-op by default."""
        return None


__all__ = [
    "CapabilityDescriptor",
    "CapabilityNotDeclaredError",
    "ChannelAdapter",
    "ChannelCapability",
    "ChannelCapabilitySet",
    "ContextReplyCapability",
    "InboundCapability",
    "LoginManagedCapability",
    "OutboundCapability",
]
