"""Tool system package — tool definitions + downstream team-aware pool.

Re-exports the migrated :mod:`src.tool_system` symbols alongside the
downstream :func:`get_team_aware_tool_list` helper.
"""

from __future__ import annotations

from .build_tool import (
    McpInfo,
    SearchOrReadResult,
    Tool,
    Tools,
    ValidationResult,
    build_tool,
    find_tool_by_name,
    tool_matches_name,
)
from .context import (
    FileReadingLimits,
    GlobLimits,
    QueryChainTracking,
    ToolContext,
    ToolUseOptions,
)
from .protocol import ToolCall, ToolResult
from .registry import (
    ToolRegistry,
    assemble_tool_pool,
    filter_tools_by_deny_rules,
    get_all_base_tools,
    get_merged_tools,
    get_tools,
)
from .team_aware_pool import get_team_aware_tool_list


__all__ = [
    "FileReadingLimits",
    "GlobLimits",
    "McpInfo",
    "QueryChainTracking",
    "SearchOrReadResult",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolUseOptions",
    "Tools",
    "ValidationResult",
    "assemble_tool_pool",
    "build_tool",
    "filter_tools_by_deny_rules",
    "find_tool_by_name",
    "get_all_base_tools",
    "get_merged_tools",
    "get_tools",
    "get_team_aware_tool_list",
    "tool_matches_name",
]
