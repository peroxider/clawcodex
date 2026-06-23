"""Facade — src/services/tool_execution/streaming_executor.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.tool_execution.streaming_executor`. This
module re-exports the public surface so existing
``from src.services.tool_execution.streaming_executor import ...`` call
sites keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.tool_execution.streaming_executor import (
    BASH_TOOL_NAME,
    MessageUpdate,
    StreamingToolExecutor,
    ToolUseBlock,
    TrackedTool,
)

__all__ = [
    "BASH_TOOL_NAME",
    "MessageUpdate",
    "StreamingToolExecutor",
    "ToolUseBlock",
    "TrackedTool",
]
