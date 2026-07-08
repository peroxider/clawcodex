"""Tests for --agent <bundle_dir> main-loop agent switching."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from clawcodex_ext.agent.agent_definitions import AgentDefinition
from clawcodex_ext.agent.agent_tool_utils import filter_tools_for_startup_agent
from clawcodex_ext.agent.constants import POS_PROXY_BASE_TOOLS
from clawcodex_ext.goal.tools import (
    CREATE_GOAL_TOOL_NAME,
    GET_GOAL_TOOL_NAME,
    UPDATE_GOAL_TOOL_NAME,
)
from clawcodex_ext.tool_system.build_tool import build_tool
from extensions.sop_converter.startup_agent import build_bundle_overview_agent_definition


def _make_tool(name: str):
    return build_tool(
        name=name,
        input_schema={"type": "object", "properties": {}},
        call=lambda _i, _c: None,
        prompt=name,
    )


class TestBundleOverviewAgentDefinition(unittest.TestCase):
    def test_builds_pos_proxy_tool_allowlist(self) -> None:
        bundle = Path("/tmp/JiuwenAgent_tool_test")
        agent = build_bundle_overview_agent_definition(
            {
                "name": "clawcodex-overview",
                "description": "Overview",
                "skills": ["core_merged-skill", "harness_merged-skill"],
            },
            bundle_dir=bundle,
        )
        self.assertIsInstance(agent, AgentDefinition)
        self.assertEqual(agent.agent_type, "clawcodex-overview")
        self.assertEqual(set(agent.tools or []), set(POS_PROXY_BASE_TOOLS))
        self.assertEqual(agent.skills, ["core_merged-skill", "harness_merged-skill"])
        self.assertEqual(agent.base_dir, str(bundle.resolve()))


class TestStartupAgentToolFilter(unittest.TestCase):
    def setUp(self) -> None:
        self.all_tools = [
            _make_tool("Read"),
            _make_tool("Write"),
            _make_tool("Skill"),
            _make_tool("ToolSearch"),
            _make_tool("Agent"),
            _make_tool("Config"),
            _make_tool("openjiuwen-agent-teams-cli-main"),
        ]
        self.startup_agent = AgentDefinition(
            agent_type="clawcodex-overview",
            when_to_use="overview",
            tools=sorted(POS_PROXY_BASE_TOOLS),
            source="dynamic",
            base_dir="dynamic",
        )

    def test_filters_to_proxy_allowlist(self) -> None:
        filtered = filter_tools_for_startup_agent(self.all_tools, self.startup_agent)
        names = {tool.name for tool in filtered}
        self.assertIn("Skill", names)
        self.assertIn("ToolSearch", names)
        self.assertIn("Agent", names)
        self.assertIn("Read", names)
        self.assertNotIn("Write", names)
        self.assertNotIn("Config", names)
        self.assertNotIn("openjiuwen-agent-teams-cli-main", names)

    def test_preserves_goal_infrastructure_tools(self) -> None:
        tools = [
            *self.all_tools,
            _make_tool(GET_GOAL_TOOL_NAME),
            _make_tool(CREATE_GOAL_TOOL_NAME),
            _make_tool(UPDATE_GOAL_TOOL_NAME),
        ]

        filtered = filter_tools_for_startup_agent(tools, self.startup_agent)
        names = {tool.name for tool in filtered}

        self.assertIn(GET_GOAL_TOOL_NAME, names)
        self.assertIn(CREATE_GOAL_TOOL_NAME, names)
        self.assertIn(UPDATE_GOAL_TOOL_NAME, names)

    def test_respects_explicit_goal_tool_disallow(self) -> None:
        agent = AgentDefinition(
            agent_type="clawcodex-overview",
            when_to_use="overview",
            tools=sorted(POS_PROXY_BASE_TOOLS),
            disallowed_tools=[UPDATE_GOAL_TOOL_NAME],
            source="dynamic",
            base_dir="dynamic",
        )
        tools = [
            *self.all_tools,
            _make_tool(GET_GOAL_TOOL_NAME),
            _make_tool(CREATE_GOAL_TOOL_NAME),
            _make_tool(UPDATE_GOAL_TOOL_NAME),
        ]

        filtered = filter_tools_for_startup_agent(tools, agent)
        names = {tool.name for tool in filtered}

        self.assertIn(GET_GOAL_TOOL_NAME, names)
        self.assertIn(CREATE_GOAL_TOOL_NAME, names)
        self.assertNotIn(UPDATE_GOAL_TOOL_NAME, names)

    def test_noop_without_startup_agent(self) -> None:
        filtered = filter_tools_for_startup_agent(self.all_tools, None)
        self.assertEqual(len(filtered), len(self.all_tools))


if __name__ == "__main__":
    unittest.main()
