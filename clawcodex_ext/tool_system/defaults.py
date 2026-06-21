from __future__ import annotations

from typing import Any, Callable

from .registry import ToolRegistry
from .tools import ALL_STATIC_TOOLS, make_agent_tool, make_tool_search_tool


def build_default_registry(
    *,
    include_user_tools: bool = True,
    provider: "Any | None" = None,
    get_available_mcp_servers: Callable[[], list[str]] | None = None,
    load_agent_tools: bool = True,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in ALL_STATIC_TOOLS:
        registry.register(tool)

    # Register extension tools (二开 tools that are not in upstream).
    try:
        from extensions.tool_system_ext.registration import EXTENSION_TOOLS

        for t in EXTENSION_TOOLS:
            registry.register(t)
    except ImportError:
        pass

    registry.register(
        make_agent_tool(
            registry,
            provider=provider,
            get_available_mcp_servers=get_available_mcp_servers,
        )
    )
    registry.register(make_tool_search_tool(registry))

    # Load persisted agent-created tools on startup.
    if load_agent_tools:
        try:
            from clawcodex_ext.tool_system.tools.create_agent_tool import load_persisted_agent_tools
            from clawcodex_ext.agent.tool_authoring.registry_ext import list_tools

            load_persisted_agent_tools()
            for tool in list_tools():
                registry.register(tool)
        except ImportError:
            pass

    return registry
