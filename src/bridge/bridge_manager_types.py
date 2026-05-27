"""Bridge state and callback types for BridgeManager.

Mirrors the TypeScript callback interfaces from useReplBridge.tsx
and initReplBridge.ts for the Python port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class BridgeState:
    """Bridge connection state values."""

    READY = "ready"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


# ── Callback Protocols ────────────────────────────────────────────────────────


class OnInboundMessage(Protocol):
    """Called when an inbound message arrives from the remote session."""

    def __call__(self, msg: dict[str, Any]) -> None: ...


class OnPermissionResponse(Protocol):
    """Called when a permission response arrives from the remote session."""

    def __call__(self, response: dict[str, Any]) -> None: ...


class OnInterrupt(Protocol):
    """Called when an interrupt is requested from the remote session."""

    def __call__(self) -> None: ...


class OnSetModel(Protocol):
    """Called when the remote session wants to change the model."""

    def __call__(self, model: str | None) -> None: ...


class OnSetMaxThinkingTokens(Protocol):
    """Called when the remote session wants to change thinking config."""

    def __call__(self, max_tokens: int | None) -> None: ...


class OnSetPermissionMode(Protocol):
    """Called when the remote session wants to change permission mode.

    Returns dict with 'ok' key (True/False) and optional 'error' key.
    """

    def __call__(self, mode: str) -> dict[str, Any]: ...


class OnStateChange(Protocol):
    """Called when bridge state changes."""

    def __call__(self, state: str, detail: str | None = None) -> None: ...


class OnUserMessage(Protocol):
    """Called when a user message is written to the bridge.

    Returns True if the callback has handled the message (e.g., derived
    the session title) and no further title derivation is needed.
    """

    def __call__(self, text: str, session_id: str) -> bool: ...


class BridgePermissionCallbacks(Protocol):
    """Permission callbacks passed to AppState for the interactive permission handler.

    Mirrors the BridgePermissionCallbacks interface used in useReplBridge.tsx.
    """

    def send_request(
        self,
        request_id: str,
        tool_name: str,
        input: dict[str, Any],
        tool_use_id: str,
        description: str,
        permission_suggestions: list[dict[str, Any]] | None = None,
        blocked_path: str | None = None,
    ) -> None: ...


class BridgePermissionResponse(Protocol):
    """A parsed permission response from the remote session."""

    @property
    def allowed(self) -> bool: ...

    @property
    def request_id(self) -> str: ...


# ── Bridge Manager State ────────────────────────────────────────────────────────


@dataclass
class BridgeManagerState:
    """Current state of the bridge manager."""

    enabled: bool = False
    connected: bool = False
    session_active: bool = False
    reconnecting: bool = False
    outbound_only: bool = False
    error: str | None = None
    session_id: str | None = None
    environment_id: str | None = None
    connect_url: str | None = None
    session_url: str | None = None
    permission_callbacks: BridgePermissionCallbacks | None = None


# ── Permission Request/Response Types ──────────────────────────────────────────


@dataclass
class PermissionRequest:
    """A permission request pending user decision."""

    request_id: str
    tool_name: str
    input: dict[str, Any] | None
    tool_use_id: str
    description: str
    permission_suggestions: list[dict[str, Any]] | None = None
    blocked_path: str | None = None
    created_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionRequest":
        return cls(
            request_id=data.get("request_id", ""),
            tool_name=data.get("tool_name", ""),
            input=data.get("input"),
            tool_use_id=data.get("tool_use_id", ""),
            description=data.get("description", ""),
            permission_suggestions=data.get("permission_suggestions"),
            blocked_path=data.get("blocked_path"),
        )


@dataclass
class PermissionResponse:
    """A permission response to send back to the bridge."""

    allowed: bool
    request_id: str
    response_data: dict[str, Any] = field(default_factory=dict)


# ── Message Types for Bridge Communication ─────────────────────────────────────


@dataclass
class BridgeMessage:
    """A message to be sent through the bridge."""

    type: str
    data: dict[str, Any]
    uuid: str | None = None


# ── Bridge Manager Config ──────────────────────────────────────────────────────


@dataclass
class BridgeManagerConfig:
    """Configuration for the BridgeManager."""

    # Identity
    working_dir: str = "."
    machine_name: str = "localhost"
    branch: str = "main"
    git_repo_url: str | None = None
    title: str = "ClawCodex Session"

    # URLs
    base_url: str = "https://api.claude.ai"
    session_ingress_url: str = "https://api.claude.ai"

    # Auth
    worker_type: str = "claude_code"
    get_access_token: Callable[[], str | None] = field(default_factory=lambda: None)

    # Optional callbacks
    on_inbound_message: OnInboundMessage | None = None
    on_permission_response: OnPermissionResponse | None = None
    on_interrupt: OnInterrupt | None = None
    on_set_model: OnSetModel | None = None
    on_set_max_thinking_tokens: OnSetMaxThinkingTokens | None = None
    on_set_permission_mode: OnSetPermissionMode | None = None
    on_state_change: OnStateChange | None = None
    on_user_message: OnUserMessage | None = None

    # Session management
    perpetual: bool = False
    outbound_only: bool = False
    initial_history_cap: int = 200

    # Initial messages for session resume
    initial_messages: list[Any] | None = None
    previously_flushed_uuids: set[str] | None = None