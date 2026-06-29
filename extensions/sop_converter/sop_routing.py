"""Runtime guards for SOP bundle agent delegation."""

from __future__ import annotations

import re
from typing import Any

from clawcodex_ext.agent.constants import POS_SOP_DOMAIN_AGENT_TOOLS

_BUILTIN_DELEGATION_TYPES = frozenset({"general-purpose", "Explore", "Plan"})

_SDK_TOOL_NAME = re.compile(r"\bopenjiuwen-[a-z0-9-]+\b", re.IGNORECASE)
_SKILL_OR_TOOLSEARCH = re.compile(r"\b(?:Skill|ToolSearch)\s*\(", re.IGNORECASE)
_SELECT_TOOL = re.compile(r"\bselect:[a-z0-9-]+\b", re.IGNORECASE)


def looks_like_direct_sdk_execution(prompt: str) -> bool:
    """True when the prompt describes Skill/ToolSearch/SDK tool work."""
    text = (prompt or "").strip()
    if not text:
        return False
    if _SDK_TOOL_NAME.search(text):
        return True
    if _SKILL_OR_TOOLSEARCH.search(text):
        return True
    if _SELECT_TOOL.search(text):
        return True
    lowered = text.lower()
    sdk_markers = (
        "team-memory-dir",
        "ensure-dir",
        "toolsearch",
        "openjiuwen_merged-skill",
        "memory-skill",
        "sdk 工具",
        "调用工具",
    )
    return any(marker in lowered for marker in sdk_markers)


def list_domain_agent_types(agent_definitions: list[Any]) -> list[str]:
    """Return bundle domain agents (``*-agent``, excluding overview)."""
    names: list[str] = []
    for agent in agent_definitions:
        agent_type = getattr(agent, "agent_type", None) or getattr(agent, "name", "")
        if not isinstance(agent_type, str):
            continue
        if not agent_type.endswith("-agent"):
            continue
        if agent_type in ("clawcodex-overview",):
            continue
        names.append(agent_type)
    return sorted(set(names))


def check_bundle_agent_delegation(
    *,
    subagent_type: str | None,
    prompt: str,
    agent_definitions: list[Any],
) -> str | None:
    """Return an error message when overview delegates SDK work to the wrong agent."""
    try:
        from extensions.sop_converter.bundle_context import get_active_bundle
    except ImportError:
        return None

    if get_active_bundle() is None:
        return None

    resolved = subagent_type or "general-purpose"
    domain_agents = list_domain_agent_types(agent_definitions)
    if not domain_agents:
        return None

    if resolved in domain_agents:
        return None

    if resolved not in _BUILTIN_DELEGATION_TYPES:
        return None

    if not looks_like_direct_sdk_execution(prompt):
        return None

    examples = ", ".join(f'Agent(subagent_type="{name}", prompt="...")' for name in domain_agents[:4])
    if len(domain_agents) > 4:
        examples += ", ..."
    return (
        f"SOP bundle mode: do not delegate SDK Skill/ToolSearch/tool execution to "
        f'"{resolved}". Use a domain agent instead ({", ".join(domain_agents)}). '
        f"Example: {examples}"
    )


def refresh_domain_agent_sop_prompts(agent_definitions: list[Any]) -> list[Any]:
    """Re-apply latest SOP domain-agent body when a bundle session is active."""
    try:
        from dataclasses import replace

        from extensions.sop_converter.bundle_context import get_active_bundle
        from extensions.sop_converter.sop_prompts import agent_type_to_skill_name, domain_agent_sop_body
    except ImportError:
        return agent_definitions

    if get_active_bundle() is None:
        return agent_definitions

    bundle = get_active_bundle()
    sdk_source_dir = bundle.sdk_source_dir if bundle is not None else None

    refreshed: list[Any] = []
    for agent in agent_definitions:
        agent_type = getattr(agent, "agent_type", "")
        if not isinstance(agent_type, str) or not agent_type.endswith("-agent"):
            refreshed.append(agent)
            continue
        if agent_type == "clawcodex-overview":
            refreshed.append(agent)
            continue
        skill_name = agent_type_to_skill_name(agent_type)
        body = domain_agent_sop_body(
            agent_type=agent_type,
            description=getattr(agent, "when_to_use", "") or "",
            skill_name=skill_name,
            sdk_source_dir=sdk_source_dir,
        )
        tools = sorted(POS_SOP_DOMAIN_AGENT_TOOLS)
        refreshed.append(
            replace(
                agent,
                tools=tools,
                get_system_prompt=_make_system_prompt_fn(body),
            )
        )
    return refreshed


def _make_system_prompt_fn(prompt_text: str):
    """Return a get_system_prompt callable with stable closure binding."""

    def _get_system_prompt(**_kwargs: Any) -> str:
        return prompt_text

    return _get_system_prompt
