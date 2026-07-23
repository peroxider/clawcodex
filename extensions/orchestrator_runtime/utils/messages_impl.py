"""Orchestrator-local message + content-block helpers (Phase 3).

AgentRunner 的 7 处 lazy import (`clawcodex_ext.types.{messages,content_blocks}`)
抽取到这里 —— 保留原 dataclass 形态，最小化迁移成本。

设计约束
========

* **不 import ``clawcodex_ext.*``** —— 与 Phase 2 同款反向耦合约束。
* 复制而非代理（copy-down），保持上游 dataclass 形态不变；Phase 3+ 如需替换
  dataclass 形态，单独走迁移路径。
* 只复制 agent_runner.py 实际使用的 4 个符号：
  - ``TextBlock`` / ``ToolUseBlock`` / ``ToolResultBlock`` (content_blocks)
  - ``create_user_message`` / ``create_assistant_message`` (messages 工厂)

Drift guard
-----------

上游 ``clawcodex_ext/types/content_blocks.py`` 与 ``messages.py`` 是 canonical，
本文件是 orchestrator 内部副本。Drift check：

.. code-block:: bash

    diff -q extensions/orchestrator_runtime/utils/messages_impl.py \\
            <(grep -A 60 'class TextBlock' clawcodex_ext/types/content_blocks.py)

期望：完全一致（直到 Phase 4+ 主动迁移）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import uuid4


# ─── Content blocks (mirrors clawcodex_ext.types.content_blocks) ───────────

@dataclass
class TextBlock:
    text: str = ""
    type: Literal["text"] = "text"


@dataclass
class ToolUseBlock:
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str = ""
    content: str | list[Any] = ""
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None


MessageContent: TypeAlias = str | list[Any]


# ─── Message factories (mirrors clawcodex_ext.types.messages) ──────────────

def _now_iso() -> str:
    return datetime.now().isoformat()


def _new_uuid() -> str:
    return str(uuid4())


def create_user_message(content: MessageContent, **kwargs: Any) -> dict[str, Any]:
    """构造一个 user message dict —— 与 ``clawcodex_ext.types.messages.create_user_message``
    1:1 形态对齐。

    只承接 agent_runner.py 实际使用的字段，**不做完整复刻**。
    """
    return {
        "role": "user",
        "content": content,
        "type": "user",
        "uuid": _new_uuid(),
        "timestamp": _now_iso(),
        **kwargs,
    }


def create_assistant_message(content: MessageContent, **kwargs: Any) -> dict[str, Any]:
    """构造一个 assistant message dict —— 与 ``create_assistant_message`` 对齐。"""
    return {
        "role": "assistant",
        "content": content,
        "type": "assistant",
        "uuid": _new_uuid(),
        "timestamp": _now_iso(),
        **kwargs,
    }


def message_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """从 wire-format dict 还原 message dict —— 简化版（agent_runner 仅在
    ``_save_json_snapshot`` 用一次，调用栈上游已有校验）。

    完整版见 ``clawcodex_ext.types.messages.message_from_dict``；本实现仅
    满足 orchestrator 内部 _save_json_snapshot 的最小需求（透传字段）。
    """
    return {
        "role": data.get("role", "user"),
        "content": data.get("content", ""),
        "type": data.get("type", data.get("role", "user")),
        "uuid": data.get("uuid") or _new_uuid(),
        "timestamp": data.get("timestamp") or _now_iso(),
        **{
            k: v
            for k, v in data.items()
            if k
            not in {
                "role",
                "content",
                "type",
                "uuid",
                "timestamp",
            }
        },
    }


__all__ = [
    "MessageContent",
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "create_user_message",
    "create_assistant_message",
    "message_from_dict",
]