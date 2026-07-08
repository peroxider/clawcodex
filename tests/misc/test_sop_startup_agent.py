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


class TestApplySopStartupRegistersBundleAgents(unittest.TestCase):
    def test_apply_sop_startup_registers_agents_and_skills(self) -> None:
        import tempfile

        from clawcodex_ext.agent.load_agents_dir import (
            clear_agent_definitions_cache,
            get_agent_definitions_with_overrides,
        )
        from clawcodex_ext.cli.dispatch import _apply_sop_startup
        from src.skills.loader import get_all_skills, get_registered_skill

        clear_agent_definitions_cache()

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            bundle = ws / "JiuwenAgent_tool_test"
            skill_dir = ws / "skills" / "JiuwenAgent_tool_test"
            agents_dir = bundle / ".claude" / "agents"
            skill_dir.mkdir(parents=True)
            agents_dir.mkdir(parents=True)

            (skill_dir / "core_merged-skill.md").write_text(
                "---\n"
                "name: core_merged-skill\n"
                "description: core domain\n"
                "user-invocable: true\n"
                "---\n\n"
                "# core\n",
                encoding="utf-8",
            )
            (agents_dir / "core_merged-agent.md").write_text(
                "---\n"
                "name: core_merged-agent\n"
                "description: Core domain agent\n"
                "tools:\n"
                "  - Skill\n"
                "  - ToolSearch\n"
                "---\n\n"
                "Run core SDK tasks.\n",
                encoding="utf-8",
            )

            ctx = MagicMock()
            ctx.tool_registry = MagicMock()
            ctx.options = MagicMock()
            ctx.tool_context = MagicMock()
            ctx.tool_context.bundle_context = None

            overview = {
                "name": "clawcodex-overview",
                "description": "Overview",
                "skills": ["core_merged-skill"],
                "system_prompt_body": "",
            }

            _apply_sop_startup(
                ctx,
                overview,
                bundle_path=bundle,
                workspace=ws,
                force_bundle=True,
            )

            self.assertEqual(ctx.options.agent_dir_override, bundle.resolve())
            self.assertEqual(ctx.tool_context._agent_dir_override, bundle.resolve())

            agent_types = {
                a.agent_type
                for a in get_agent_definitions_with_overrides(str(bundle.resolve()))
            }
            self.assertIn("core_merged-agent", agent_types)

            get_all_skills(project_root=ws)
            self.assertIsNotNone(get_registered_skill("core_merged-skill"))


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
