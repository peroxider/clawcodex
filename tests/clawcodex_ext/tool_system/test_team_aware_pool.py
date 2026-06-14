"""Unit tests for clawcodex_ext.tool_system.team_aware_pool.

Covers the high-level wrapper that pulls the full tool list from a
ToolRegistry and applies the team-context filter in one call. This is
the entry point used by ``src/query/agent_loop_compat.py`` and
``clawcodex_ext/repl/core.py`` to materialize the model-facing tool
list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pytest

from clawcodex_ext.tool_system import get_team_aware_tool_list
from src.tool_system.context import ToolContext
from src.tool_system.registry import ToolRegistry


@dataclass
class _FakeTool:
    name: str
    aliases: tuple[str, ...] = ()


def _build_registry_with(*tool_names: str) -> ToolRegistry:
    """Build a minimal ToolRegistry populated with the given tool names.

    Avoids depending on the real ``src.tool_system.tools.ALL_STATIC_TOOLS``
    (which is a moving target across PRs) — we only need the registry
    contract: ``list_tools()`` returns a list of objects with a
    ``name`` attribute.
    """
    registry = ToolRegistry()
    for n in tool_names:
        registry.register(_FakeTool(name=n))
    return registry


def test_get_team_aware_tool_list_drops_send_message_when_no_team() -> None:
    registry = _build_registry_with("Read", "Bash", "SendMessage", "Edit")
    result = get_team_aware_tool_list(registry, team=None)
    assert [t.name for t in result] == ["Read", "Bash", "Edit"]


def test_get_team_aware_tool_list_keeps_all_when_team_active() -> None:
    registry = _build_registry_with(
        "Read", "Bash", "SendMessage", "TeamCreate", "TeamDelete", "Edit",
    )
    team = {"team_name": "t", "lead_agent_id": "lead-1"}
    result = get_team_aware_tool_list(registry, team=team)
    assert [t.name for t in result] == [
        "Read", "Bash", "SendMessage", "TeamCreate", "TeamDelete", "Edit",
    ]


def test_get_team_aware_tool_list_keeps_all_when_team_is_empty_dict() -> None:
    # Empty dict is "no team active" per has_team_context — drops
    # team-only tools.
    registry = _build_registry_with("Read", "SendMessage")
    result = get_team_aware_tool_list(registry, team={})
    assert [t.name for t in result] == ["Read"]


def test_get_team_aware_tool_list_drops_team_create_delete_when_no_team() -> None:
    # ``TeamCreate`` / ``TeamDelete`` only make sense once a team
    # exists; the filter drops them so the model can't accidentally
    # call them out of order.
    registry = _build_registry_with(
        "Read", "TeamCreate", "TeamDelete", "Bash",
    )
    result = get_team_aware_tool_list(registry, team=None)
    assert [t.name for t in result] == ["Read", "Bash"]


def test_get_team_aware_tool_list_empty_registry() -> None:
    registry = ToolRegistry()
    result = get_team_aware_tool_list(registry, team=None)
    assert result == []


def test_get_team_aware_tool_list_returns_list_type() -> None:
    # The downstream QueryParams expects a list (it indexes + iterates).
    registry = _build_registry_with("Read")
    result = get_team_aware_tool_list(registry, team=None)
    assert isinstance(result, list)
