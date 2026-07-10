"""Tests for REPL/TUI @agent- mention agent discovery."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from clawcodex_ext.agent.load_agents_dir import (
    clear_agent_definitions_cache,
    get_agents_for_mentions,
    resolve_agent_dir_override,
)

BUNDLE = Path(__file__).resolve().parents[2] / ".clawcodex" / "AutoResearchClaw3"


class TestAgentsForMentions(unittest.TestCase):
    def setUp(self) -> None:
        clear_agent_definitions_cache()

    def test_resolve_from_tool_context_agent_dir_override(self) -> None:
        if not BUNDLE.is_dir():
            self.skipTest("AutoResearchClaw3 bundle not present")
        tc = SimpleNamespace(_agent_dir_override=BUNDLE)
        resolved = resolve_agent_dir_override(tool_context=tc)
        self.assertEqual(resolved, BUNDLE.resolve())

    def test_bundle_agents_merged_for_mentions(self) -> None:
        if not BUNDLE.is_dir():
            self.skipTest("AutoResearchClaw3 bundle not present")
        ws = BUNDLE.parents[1]
        tc = SimpleNamespace(_agent_dir_override=BUNDLE)
        agents = get_agents_for_mentions(ws, tool_context=tc)
        types = {a.agent_type for a in agents}
        self.assertIn("AutoResearchClaw-topic-init-agent", types)

    def test_resolve_from_runtime_bundle_path(self) -> None:
        if not BUNDLE.is_dir():
            self.skipTest("AutoResearchClaw3 bundle not present")
        rc = SimpleNamespace(options=SimpleNamespace(
            agent_dir_override=None,
            bundle_path=BUNDLE,
        ))
        resolved = resolve_agent_dir_override(runtime_context=rc)
        self.assertEqual(resolved, BUNDLE.resolve())
