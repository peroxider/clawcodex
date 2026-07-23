"""Orchestrator Runtime — Protocol 骨架（Phase 1）。

本目录仅声明 Protocol，不含实现。所有 Protocol 必须满足
"无 import 上游"约束（不允许 ``import clawcodex_ext.*`` /
``import src.*`` / ``import extensions.orchestrator.*``）。
具体契约详见 ``docs/ORCHESTRATOR_DECOUPLING_DESIGN.md`` §4。
"""

from __future__ import annotations

from .agent_runtime import AgentRuntime, SessionContext
from .backend import BackendUnavailable, OrchestratordBackend
from .coordinator import CoordinatorContextProvider
from .diagnostics import DiagnosticsProbe, HeartbeatState, HeartbeatStatus
from .git_backend import FileStatusLike, GitBackend
from .im_channel import ImChannel, ImCommandRouter, ImInbound, ImOutbound
from .intent_focus import FocusArea, IntentFocus, IssueLike
from .messages import (
    AgentEvent,
    AgentEventType,
    PhaseComplete,
    SessionComplete,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)
from .provider import LLMProvider
from .session_storage import ConversationLike, SessionMeta, SessionStorage
from .workspace_tooling import ToolContextLike, WorkspaceTooling

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "AgentRuntime",
    "BackendUnavailable",
    "ConversationLike",
    "CoordinatorContextProvider",
    "DiagnosticsProbe",
    "FileStatusLike",
    "FocusArea",
    "GitBackend",
    "HeartbeatState",
    "HeartbeatStatus",
    "ImChannel",
    "ImCommandRouter",
    "ImInbound",
    "ImOutbound",
    "IntentFocus",
    "IssueLike",
    "LLMProvider",
    "OrchestratordBackend",
    "PhaseComplete",
    "SessionComplete",
    "SessionContext",
    "SessionMeta",
    "SessionStorage",
    "TextDelta",
    "ToolCallEvent",
    "ToolContextLike",
    "ToolResultEvent",
    "WorkspaceTooling",
]
