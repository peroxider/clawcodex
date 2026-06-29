"""Tests for SOP-to-agent lazy tool loading (deferred schemas + skill filter)."""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from clawcodex_ext.agent.constants import POS_PROXY_BASE_TOOLS, SKILL_CONTEXT_BASE_TOOLS
from clawcodex_ext.agent.prompt import _get_tools_description
from clawcodex_ext.agent.tool_authoring.factory import build_tool_from_spec
from clawcodex_ext.agent.tool_authoring.spec import AgentToolSpec
from clawcodex_ext.query.query import QueryParams, _resolve_effective_tools
from clawcodex_ext.tool_system.build_tool import build_tool
from clawcodex_ext.tool_system.context import ToolContext, ToolUseOptions
from clawcodex_ext.tool_system.registry import ToolRegistry
from clawcodex_ext.tool_system.tools.skill import _build_context_modifier


def _make_agent_def(*, tool_names: list[str] | None) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        agent_type="test-agent",
        when_to_use="test",
        tools=tool_names,
        disallowed_tools=None,
    )


class TestPosConverterDeferredTools(unittest.TestCase):
    def test_pos_converter_tools_are_deferred(self) -> None:
        spec = AgentToolSpec(
            name="task-loop-should-continue",
            description="Check loop continuation",
            input_schema={"type": "object", "properties": {}},
            call_type="bash",
            call_impl="python3 /tmp/wrapper.py should_continue '{}'",
            source="pos-converter",
        )
        tool = build_tool_from_spec(spec)
        self.assertTrue(tool.should_defer)

    def test_agent_created_tools_not_deferred(self) -> None:
        spec = AgentToolSpec(
            name="my-custom-tool",
            description="Custom",
            input_schema={"type": "object", "properties": {}},
            call_type="bash",
            call_impl="echo hi",
            source="agent-created",
        )
        tool = build_tool_from_spec(spec)
        self.assertFalse(tool.should_defer)


class TestAgentPromptTruncation(unittest.TestCase):
    def test_large_tool_list_shows_count(self) -> None:
        agent = _make_agent_def(tool_names=[f"tool-{i}" for i in range(50)])
        desc = _get_tools_description(agent)
        self.assertIn("50 tools", desc)
        self.assertIn("ToolSearch", desc)


class TestSkillContextModifier(unittest.TestCase):
    def test_allowed_tools_filters_options_tools(self) -> None:
        @dataclass
        class _Skill:
            allowed_tools: list[str] = field(
                default_factory=lambda: ["domain-tool-a", "domain-tool-b"]
            )
            model: str | None = None
            effort: str | None = None

        registry = ToolRegistry()
        base = build_tool(
            name="Read",
            input_schema={"type": "object", "properties": {}},
            call=lambda _i, _c: None,
        )
        domain_a = build_tool(
            name="domain-tool-a",
            input_schema={"type": "object", "properties": {}},
            call=lambda _i, _c: None,
        )
        domain_b = build_tool(
            name="domain-tool-b",
            input_schema={"type": "object", "properties": {}},
            call=lambda _i, _c: None,
        )
        other = build_tool(
            name="unrelated-tool",
            input_schema={"type": "object", "properties": {}},
            call=lambda _i, _c: None,
        )
        for t in (base, domain_a, domain_b, other):
            registry.register(t)

        ctx = ToolContext(
            options=ToolUseOptions(tools=list(registry.list_tools())),
            tool_registry=registry,
            workspace_root=".",
        )
        modifier = _build_context_modifier(_Skill())
        assert modifier is not None
        modifier(ctx)

        names = {t.name for t in ctx.options.tools}
        self.assertIn("Read", names)
        self.assertIn("domain-tool-a", names)
        self.assertIn("domain-tool-b", names)
        self.assertNotIn("unrelated-tool", names)


class TestResolveEffectiveTools(unittest.TestCase):
    def test_defers_pos_converter_tools_when_tool_search_enabled(self) -> None:
        os.environ["ENABLE_TOOL_SEARCH"] = "true"

        base = build_tool(
            name="Skill",
            input_schema={"type": "object", "properties": {}},
            call=lambda _i, _c: None,
        )
        deferred = build_tool(
            name="openjiuwen-harness-task-loop-should-continue",
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "string"}},
            },
            call=lambda _i, _c: None,
            should_defer=True,
        )
        registry = ToolRegistry()
        registry.register(base)
        registry.register(deferred)

        ctx = ToolContext(
            options=ToolUseOptions(),
            tool_registry=registry,
            workspace_root=".",
        )
        provider = MagicMock()
        provider.model = "claude-sonnet-4-6"

        params = QueryParams(
            messages=[],
            system_prompt="test",
            tools=list(registry.list_tools()),
            tool_registry=registry,
            tool_use_context=ctx,
            provider=provider,
            abort_controller=MagicMock(),
        )

        effective = _resolve_effective_tools(params, ctx, [])
        names = {t.name for t in effective}
        self.assertIn("Skill", names)
        self.assertNotIn("openjiuwen-harness-task-loop-should-continue", names)


class TestPosProxyBaseTools(unittest.TestCase):
    def test_proxy_tools_include_skill_and_toolsearch(self) -> None:
        self.assertIn("Skill", POS_PROXY_BASE_TOOLS)
        self.assertIn("ToolSearch", POS_PROXY_BASE_TOOLS)

    def test_skill_base_tools_include_skill_and_toolsearch(self) -> None:
        self.assertIn("skill", SKILL_CONTEXT_BASE_TOOLS)
        self.assertIn("toolsearch", SKILL_CONTEXT_BASE_TOOLS)


if __name__ == "__main__":
    unittest.main()
