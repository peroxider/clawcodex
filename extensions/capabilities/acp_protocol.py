"""ACP Protocol — Agent Client Protocol contract.

Defines the data model and Protocol interfaces for the Agent Client
Protocol used by Zed / Cursor / Trae IDE integrations. This module is a
pure contract layer (Layer 2 ``extensions/capabilities/``): it has no
runtime dependencies and only declares signatures, mirroring the
existing :mod:`extensions.capabilities.tool_protocol` style.

Concrete transports (stdio / WebSocket) and servers live in
``extensions/trae/`` and future ``extensions/zed`` / ``extensions/cursor``
modules. See ``docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md``
for the design doc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Protocol, runtime_checkable

__all__ = [
    "ACPMessageType",
    "ACPMessageRole",
    "ACPMessage",
    "ACPSession",
    "ACPTransport",
    "ACPServer",
    "ACPToolSpec",
]


class ACPMessageType(str, Enum):
    """ACP 消息类型枚举（JSON-RPC method 命名空间）。"""

    SESSION_CREATE = "session/create"
    SESSION_RESUME = "session/resume"
    SESSION_END = "session/end"
    MESSAGE_SEND = "message/send"
    MESSAGE_STREAM = "message/stream"
    TOOL_CALL = "tool/call"
    TOOL_RESULT = "tool/result"
    SKILL_INVOKE = "skill/invoke"
    SKILL_RESULT = "skill/result"
    ERROR = "error"


class ACPMessageRole(str, Enum):
    """消息角色（对齐 OpenAI/Anthropic chat 角色）。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


def _utc_now_iso() -> str:
    """Timezone-aware UTC ISO timestamp (avoids deprecated ``datetime.utcnow``)."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ACPMessage:
    """ACP 协议消息体（JSON-RPC over WebSocket/stdio）。

    ``content`` 允许 str / dict / None 以承载文本或多模态块。
    """

    type: ACPMessageType
    id: str = ""
    session_id: str = ""
    role: ACPMessageRole = ACPMessageRole.USER
    content: str | dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (enum → str)."""
        return {
            "type": self.type.value,
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ACPMessage":
        """Deserialize from a dict (str → enum, tolerant of missing fields)."""
        raw_type = data.get("type", "")
        try:
            msg_type = ACPMessageType(raw_type)
        except ValueError:
            msg_type = ACPMessageType.ERROR
            data.setdefault("metadata", {})["unknown_type"] = raw_type
        raw_role = data.get("role", "user")
        try:
            role = ACPMessageRole(raw_role)
        except ValueError:
            role = ACPMessageRole.USER
        return cls(
            type=msg_type,
            id=data.get("id", ""),
            session_id=data.get("session_id", ""),
            role=role,
            content=data.get("content"),
            tool_calls=data.get("tool_calls"),
            tool_results=data.get("tool_results"),
            metadata=data.get("metadata", {}) or {},
            timestamp=data.get("timestamp", _utc_now_iso()),
        )


@dataclass
class ACPSession:
    """ACP 会话状态（服务端持有，可序列化持久化）。"""

    id: str
    created_at: str = field(default_factory=_utc_now_iso)
    messages: list[ACPMessage] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    workspace_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def append(self, msg: ACPMessage) -> None:
        """Record a message in this session's history."""
        self.messages.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "messages": [m.to_dict() for m in self.messages],
            "skills": list(self.skills),
            "workspace_path": self.workspace_path,
            "metadata": self.metadata,
        }


@dataclass
class ACPToolSpec:
    """ACP 暴露的工具规格（用于 ``tools/list`` 响应）。"""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ACPTransport(Protocol):
    """ACP 传输层抽象（stdio / WebSocket / TCP）。

    实现者负责把 :class:`ACPMessage` 序列化为底层协议帧并在
    :meth:`receive` 中反序列化。``receive`` 返回 ``None`` 表示流
    末尾（EOF / 连接关闭）。
    """

    async def connect(self) -> None: ...

    async def send(self, msg: ACPMessage) -> None: ...

    async def receive(self) -> ACPMessage | None: ...

    async def close(self) -> None: ...


@runtime_checkable
class ACPServer(Protocol):
    """ACP 协议服务端（接收 IDE 发起的会话请求）。

    ``process_message`` 返回异步迭代器以支持流式响应（对应
    ``message/stream``）。``invoke_skill`` 为同步语义的 skill 调用
    入口（P66-D 桥接层使用）。
    """

    async def handle_session(self, transport: ACPTransport) -> None: ...

    async def create_session(self, workspace_path: str) -> ACPSession: ...

    async def resume_session(self, session_id: str) -> ACPSession | None: ...

    def process_message(self, msg: ACPMessage) -> AsyncIterator[ACPMessage]: ...

    async def invoke_skill(self, skill_name: str, params: dict[str, Any]) -> dict[str, Any]: ...
