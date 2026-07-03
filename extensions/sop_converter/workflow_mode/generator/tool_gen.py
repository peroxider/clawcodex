"""Build frontmatter tool lists from capability profiles."""

from __future__ import annotations

from clawcodex_ext.agent.constants import POS_SOP_DOMAIN_AGENT_TOOLS

from ..capability.models import ExecutionMode, StageCapabilityProfile


def stage_agent_tool_names(sdk_tools: list[str]) -> list[str]:
    """SOP stage agents need Skill/ToolSearch plus deferred SDK tools."""
    return sorted(set(POS_SOP_DOMAIN_AGENT_TOOLS) | set(sdk_tools))


def tools_for_profile(
    profile: StageCapabilityProfile,
    *,
    bridge_tool: str | None = None,
) -> list[str]:
    tools = list(profile.recommended_tools)
    if profile.execution_mode in (ExecutionMode.WRAPPER, ExecutionMode.HYBRID) and bridge_tool:
        if bridge_tool not in tools:
            tools.append(bridge_tool)
    return tools
