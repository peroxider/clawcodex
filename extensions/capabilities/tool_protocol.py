"""ToolSystem Protocol — interface for the tool registry and execution.

This Protocol defines the contract for tool system operations.
Concrete implementation is in src/tool_system/registry.py and build_tool.py.

See: src/tool_system/agent_loop.py imports from tool_system.registry
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.permissions.types import ToolPermissionContext
    from src.tool_system.build_tool import Tool
    from src.tool_system.context import ToolContext
    from src.tool_system.protocol import ToolCall, ToolResult
    from src.tool_system.registry import ToolRegistry

__all__ = ["ToolSystemProtocol"]


class ToolSystemProtocol(Protocol):
    """Protocol for tool registry and tool execution.

    Implementors must provide:
      - get_tools() -> list[Tool]
      - find_tool_by_name(name) -> Tool | None
      - build_tool(tool_def) -> Tool
      - assemble_tool_pool(...) -> list[Tool]
      - dispatch(call, context) -> ToolResult
    """

    def get_tools(self) -> "list[Tool]": ...  # pragma: no cover

    def find_tool_by_name(self, name: str) -> "Tool | None": ...  # pragma: no cover

    def build_tool(self, tool_def: dict[str, object]) -> "Tool": ...  # pragma: no cover

    def assemble_tool_pool(
        self,
        registry: "ToolRegistry",
        permission_context: "ToolPermissionContext",
        mcp_tools: "list[Tool] | None" = None,
    ) -> "list[Tool]": ...  # pragma: no cover

    def dispatch(
        self, call: "ToolCall", context: "ToolContext"
    ) -> "ToolResult": ...  # pragma: no cover
