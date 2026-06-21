"""Team-aware tool pool assembly.

Higher-level wrapper around :func:`extensions.tool_system_ext.team_filter.filter_team_only_tools`
that pulls the full tool list from a ``ToolRegistry`` and applies the
team-context filter in one call. This is the single entry point the
caller sites in ``src/query/agent_loop_compat.py`` and
``clawcodex_ext/repl/core.py`` use to materialize their model-facing
tool list.

Decoupling rationale: the upstream tool system (``src/tool_system``)
owns tool definitions, the extension layer (``extensions/`` and
``clawcodex_ext/``) owns the policy of which tools are visible under
which conditions. Putting the policy in extensions means a single
deployment can override the visibility rule without forking the
upstream registry code.
"""

from __future__ import annotations

from extensions.tool_system_ext.team_filter import (
    filter_team_only_tools,
    has_team_context,
)


def get_team_aware_tool_list(
    registry: ToolRegistry,
    team: object,
) -> list:
    """Return the registry's tool list, with team-only tools hidden
    when ``team`` indicates no active team context.

    Args:
        registry: The :class:`ToolRegistry` to enumerate.
        team: The value of ``ToolContext.team`` (a dict when active,
            ``None`` or anything else when not).

    Returns:
        A list of tools, in the registry's natural order, with
        ``SendMessage`` / ``TeamCreate`` / ``TeamDelete`` removed
        when no team is active.
    """
    tools = registry.list_tools()
    return filter_team_only_tools(tools, has_team_context(team))


__all__ = [
    "get_team_aware_tool_list",
]
