"""ToolSystem Protocol — interface for the tool registry and execution.

This Protocol defines the contract for tool system operations.
Concrete implementation is in src/tool_system/registry.py and build_tool.py.

See: src/tool_system/agent_loop.py imports from tool_system.registry
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol

from clawcodex_ext.tool_system.protocol import ToolCall, ToolResult

__all__ = [
    "ToolContextProtocol",
    "ToolPermissionContextProtocol",
    "ToolProtocol",
    "ToolRegistryProtocol",
    "ToolSystemProtocol",
]


class ToolPermissionContextProtocol(Protocol):
    """Protocol for permission context passed to tool assembly/dispatch."""

    mode: str
    is_bypass_permissions_mode_available: bool
    should_avoid_permission_prompts: bool

    def blocks(self, tool_name: str) -> bool: ...  # pragma: no cover


class ToolProtocol(Protocol):
    """Protocol for a single tool definition."""

    name: str
    aliases: tuple[str, ...]

    def matches_name(self, name: str) -> bool: ...  # pragma: no cover


class ToolContextProtocol(Protocol):
    """Protocol for the execution context passed to tool dispatch."""

    workspace_root: Path | None
    cwd: Path | None
    plan_mode: bool
    permission_context: ToolPermissionContextProtocol | None


class ToolRegistryProtocol(Protocol):
    """Protocol for a registry of available tools."""

    def register(self, tool: ToolProtocol) -> None: ...  # pragma: no cover

    def unregister(self, name: str) -> bool: ...  # pragma: no cover

    def get(self, name: str) -> ToolProtocol | None: ...  # pragma: no cover

    def list_tools(self) -> list[ToolProtocol]: ...  # pragma: no cover

    def dispatch(
        self, call: ToolCall, context: ToolContextProtocol
    ) -> ToolResult: ...  # pragma: no cover


class ToolSystemProtocol(Protocol):
    """Protocol for tool registry and tool execution.

    Implementors must provide:
      - get_tools() -> list[Tool]
      - find_tool_by_name(name) -> Tool | None
      - build_tool(tool_def) -> Tool
      - assemble_tool_pool(...) -> list[Tool]
      - dispatch(call, context) -> ToolResult
    """

    def get_tools(self) -> list[ToolProtocol]: ...  # pragma: no cover

    def find_tool_by_name(self, name: str) -> ToolProtocol | None: ...  # pragma: no cover

    def build_tool(self, tool_def: dict[str, object]) -> ToolProtocol: ...  # pragma: no cover

    def assemble_tool_pool(
        self,
        registry: ToolRegistryProtocol,
        permission_context: ToolPermissionContextProtocol,
        mcp_tools: list[ToolProtocol] | None = None,
    ) -> list[ToolProtocol]: ...  # pragma: no cover

    def dispatch(
        self, call: ToolCall, context: ToolContextProtocol
    ) -> ToolResult: ...  # pragma: no cover
