"""Tests for SOP bundle agent delegation guards."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from extensions.sop_converter.sop_routing import (
    check_bundle_agent_delegation,
    looks_like_direct_sdk_execution,
)


class TestSopRouting(unittest.TestCase):
    def test_looks_like_direct_sdk_execution(self) -> None:
        self.assertTrue(
            looks_like_direct_sdk_execution(
                "Skill(openjiuwen_merged-skill) then team-memory-dir"
            )
        )
        self.assertTrue(
            looks_like_direct_sdk_execution(
                "call openjiuwen-agent-teams-team-memory-dir with team_name"
            )
        )
        self.assertFalse(looks_like_direct_sdk_execution("summarize the conversation"))

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_blocks_general_purpose_for_sdk_prompt(self, mock_bundle) -> None:
        mock_bundle.return_value = SimpleNamespace(bundle_name="JiuwenAgent_tool_test")
        agents = [
            SimpleNamespace(agent_type="openjiuwen_merged-agent"),
            SimpleNamespace(agent_type="memory-agent"),
        ]
        err = check_bundle_agent_delegation(
            subagent_type="general-purpose",
            prompt="Skill(openjiuwen_merged-skill) and openjiuwen-agent-teams-team-memory-dir",
            agent_definitions=agents,
        )
        self.assertIsNotNone(err)
        self.assertIn("openjiuwen_merged-agent", err or "")

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_allows_domain_agent(self, mock_bundle) -> None:
        mock_bundle.return_value = SimpleNamespace(bundle_name="JiuwenAgent_tool_test")
        agents = [SimpleNamespace(agent_type="memory-agent")]
        err = check_bundle_agent_delegation(
            subagent_type="memory-agent",
            prompt="ensure-dir with Skill(memory-skill)",
            agent_definitions=agents,
        )
        self.assertIsNone(err)

    @patch("extensions.sop_converter.bundle_context.get_active_bundle")
    def test_no_bundle_is_noop(self, mock_bundle) -> None:
        mock_bundle.return_value = None
        err = check_bundle_agent_delegation(
            subagent_type="general-purpose",
            prompt="openjiuwen-agent-teams-team-memory-dir",
            agent_definitions=[],
        )
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
