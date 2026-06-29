"""Build the main-loop AgentDefinition for ``--agent <bundle_dir>`` startup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawcodex_ext.agent.agent_definitions import AgentDefinition
from clawcodex_ext.agent.constants import POS_PROXY_BASE_TOOLS


def build_bundle_overview_agent_definition(
    agent: dict[str, Any],
    *,
    bundle_dir: Path,
) -> AgentDefinition:
    """Turn a parsed overview agent dict into the REPL main-loop definition.

    Uses ``POS_PROXY_BASE_TOOLS`` so the session starts with Skill +
    ToolSearch + delegation tools instead of the general-purpose wildcard.
    """
    name = str(agent.get("name") or "clawcodex-overview")
    raw_skills = agent.get("skills")
    skills: list[str] | None = None
    if isinstance(raw_skills, list):
        skills = [s for s in raw_skills if isinstance(s, str)]

    return AgentDefinition(
        agent_type=name,
        when_to_use=str(agent.get("description") or ""),
        tools=sorted(POS_PROXY_BASE_TOOLS),
        skills=skills,
        source="dynamic",
        base_dir=str(bundle_dir.resolve()),
        model=agent.get("model") if isinstance(agent.get("model"), str) else None,
        get_system_prompt=lambda **_kwargs: "",
    )
