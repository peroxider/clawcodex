"""F-46: permission_mode 正交拆分 — unit tests.

Covers:

* :func:`translate_legacy_permission_mode` — translation table for all
  known modes plus edge cases.
* :class:`AgentConfig` — new ``audit_log``, ``interactive``,
  ``default_decision`` fields and their defaults.
* :class:`WorkflowConfig.from_dict` — YAML parsing of the new fields.
* :class:`AgentRunner._append_tool_event_log` — audit_log granularity
  filtering (none / minimal / full).
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from extensions.orchestrator.agent_runner import AgentRunner, AgentSession
from extensions.orchestrator.approval_policy import ToolCallEvent
from extensions.orchestrator.config.schema import (
    AgentConfig,
    SandboxConfig,
    WorkflowConfig,
)
from extensions.orchestrator.permission_translate import (
    LEGACY_MODE_TABLE,
    OrthogonalPermission,
    resolve_orthogonal_fields,
    translate_legacy_permission_mode,
)


class TestPermissionModeToThreeFields(unittest.TestCase):
    """Translate legacy permission_mode into (interactive, default_decision, audit_log)."""

    def _translate(self, mode: str) -> OrthogonalPermission:
        return translate_legacy_permission_mode(mode)

    def test_default_mode(self) -> None:
        perm = self._translate("default")
        self.assertTrue(perm.interactive)
        self.assertEqual(perm.default_decision, "ask")
        self.assertEqual(perm.audit_log, "minimal")

    def test_plan_mode(self) -> None:
        perm = self._translate("plan")
        self.assertTrue(perm.interactive)
        self.assertEqual(perm.default_decision, "deny")
        self.assertEqual(perm.audit_log, "minimal")

    def test_accept_edits_mode(self) -> None:
        perm = self._translate("acceptEdits")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "ask")
        self.assertEqual(perm.audit_log, "minimal")

    def test_bypass_permissions_mode(self) -> None:
        perm = self._translate("bypassPermissions")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "full")

    def test_dont_ask_mode(self) -> None:
        perm = self._translate("dontAsk")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "minimal")

    def test_lowercase_normalization(self) -> None:
        perm = self._translate("BYPASSPERMISSIONS")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "full")

    def test_snake_case_alias(self) -> None:
        perm = self._translate("accept_edits")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "ask")
        self.assertEqual(perm.audit_log, "minimal")

    def test_whitespace_tolerance(self) -> None:
        perm = self._translate("  bypassPermissions  ")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "full")

    def test_none_input_returns_safe_defaults(self) -> None:
        perm = self._translate(None)
        self.assertTrue(perm.interactive)
        self.assertEqual(perm.default_decision, "ask")
        self.assertEqual(perm.audit_log, "minimal")

    def test_all_legacy_modes_have_table_entries(self) -> None:
        expected = {"default", "plan", "bypasspermissions", "acceptedits", "dontask"}
        self.assertEqual(set(LEGACY_MODE_TABLE.keys()), expected)


class TestAgentConfigOrthogonalFields(unittest.TestCase):
    """New AgentConfig fields have correct defaults and accept YAML values."""

    def test_default_values(self) -> None:
        cfg = AgentConfig()
        self.assertEqual(cfg.audit_log, "minimal")
        self.assertTrue(cfg.interactive)
        self.assertEqual(cfg.default_decision, "deny")

    def test_custom_audit_log_full(self) -> None:
        cfg = AgentConfig(audit_log="full")
        self.assertEqual(cfg.audit_log, "full")

    def test_custom_audit_log_none(self) -> None:
        cfg = AgentConfig(audit_log="none")
        self.assertEqual(cfg.audit_log, "none")

    def test_custom_interactive_false(self) -> None:
        cfg = AgentConfig(interactive=False)
        self.assertFalse(cfg.interactive)

    def test_custom_default_decision_allow(self) -> None:
        cfg = AgentConfig(default_decision="allow")
        self.assertEqual(cfg.default_decision, "allow")

    def test_custom_default_decision_deny(self) -> None:
        cfg = AgentConfig(default_decision="deny")
        self.assertEqual(cfg.default_decision, "deny")


class TestWorkflowConfigOrthogonalFields(unittest.TestCase):
    """WorkflowConfig.from_dict forwards orthogonal fields with proper defaults."""

    def test_defaults_when_not_specified(self) -> None:
        wf = WorkflowConfig.from_dict({})
        self.assertEqual(wf.agent.audit_log, "minimal")
        self.assertTrue(wf.agent.interactive)
        self.assertEqual(wf.agent.default_decision, "deny")

    def test_custom_audit_log_from_yaml(self) -> None:
        wf = WorkflowConfig.from_dict({"agent": {"audit_log": "full"}})
        self.assertEqual(wf.agent.audit_log, "full")

    def test_custom_interactive_from_yaml(self) -> None:
        wf = WorkflowConfig.from_dict({"agent": {"interactive": False}})
        self.assertFalse(wf.agent.interactive)

    def test_custom_default_decision_from_yaml(self) -> None:
        wf = WorkflowConfig.from_dict({"agent": {"default_decision": "allow"}})
        self.assertEqual(wf.agent.default_decision, "allow")

    def test_combined_fields_from_yaml(self) -> None:
        wf = WorkflowConfig.from_dict({
            "agent": {
                "audit_log": "full",
                "interactive": False,
                "default_decision": "allow",
            }
        })
        self.assertEqual(wf.agent.audit_log, "full")
        self.assertFalse(wf.agent.interactive)
        self.assertEqual(wf.agent.default_decision, "allow")


class TestResolveOrthogonalFields(unittest.TestCase):
    """Test the resolve_orthogonal_fields resolution logic."""

    def test_all_none_returns_safe_defaults(self) -> None:
        perm = resolve_orthogonal_fields(permission_mode=None)
        self.assertTrue(perm.interactive)
        self.assertEqual(perm.default_decision, "ask")
        self.assertEqual(perm.audit_log, "minimal")

    def test_explicit_new_fields_override_legacy(self) -> None:
        perm = resolve_orthogonal_fields(
            permission_mode="dontAsk",
            interactive=True,
            default_decision="allow",
            audit_log="full",
        )
        self.assertTrue(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "full")

    def test_partial_override(self) -> None:
        perm = resolve_orthogonal_fields(
            permission_mode="bypassPermissions",
            audit_log="minimal",
        )
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "minimal")

    def test_legacy_only(self) -> None:
        perm = resolve_orthogonal_fields(permission_mode="bypassPermissions")
        self.assertFalse(perm.interactive)
        self.assertEqual(perm.default_decision, "allow")
        self.assertEqual(perm.audit_log, "full")

    def test_invalid_audit_log_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_orthogonal_fields(permission_mode=None, audit_log="invalid")

    def test_invalid_default_decision_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_orthogonal_fields(permission_mode=None, default_decision="invalid")


class TestAgentRunnerAuditLogResolution(unittest.TestCase):
    """Verify _resolve_audit_log resolves correctly from config."""

    def test_explicit_audit_log_used_directly(self) -> None:
        runner = AgentRunner(AgentConfig(audit_log="full"), SandboxConfig())
        self.assertEqual(runner._resolve_audit_log(), "full")

    def test_none_audit_log_falls_back_to_legacy(self) -> None:
        runner = AgentRunner(AgentConfig(permission_mode="bypassPermissions", audit_log=None), SandboxConfig())
        self.assertEqual(runner._resolve_audit_log(), "full")

    def test_default_audit_log_is_minimal(self) -> None:
        runner = AgentRunner(AgentConfig(), SandboxConfig())
        self.assertEqual(runner._resolve_audit_log(), "minimal")


class TestAppendToolEventLogAuditFiltering(unittest.TestCase):
    """Verify that audit_log=none/minimal/full controls what gets written."""

    def setUp(self) -> None:
        self._home = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._home.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._home.cleanup()

    def _make_event(self, approved: bool) -> ToolCallEvent:
        return ToolCallEvent(
            tool_name="Bash",
            params={"command": "echo hi"},
            _approved=approved,
            _deny_reason=None if approved else "denied",
        )

    def _run_with_ctx(self, runner: AgentRunner, event: ToolCallEvent, ctx: dict) -> None:
        runner._append_tool_event_log(event, ctx)

    def test_audit_log_none_skips_all_writes(self) -> None:
        runner = AgentRunner(AgentConfig(), SandboxConfig())
        ctx = {
            "run_id": "run-none",
            "permission_mode": "bypassPermissions",
            "audit_log": "none",
            "turn": 0,
        }
        self._run_with_ctx(runner, self._make_event(True), ctx)
        self._run_with_ctx(runner, self._make_event(False), ctx)
        log_path = (
            Path(os.environ["HOME"]) / ".clawcodex" / "tool-events" / "run-none" / "events.ndjson"
        )
        self.assertFalse(log_path.exists(), "audit_log=none should not create log file")

    def test_audit_log_minimal_only_logs_denies(self) -> None:
        runner = AgentRunner(AgentConfig(), SandboxConfig())
        ctx = {
            "run_id": "run-minimal",
            "permission_mode": "bypassPermissions",
            "audit_log": "minimal",
            "turn": 0,
        }
        self._run_with_ctx(runner, self._make_event(True), ctx)
        self._run_with_ctx(runner, self._make_event(False), ctx)
        log_path = (
            Path(os.environ["HOME"]) / ".clawcodex" / "tool-events" / "run-minimal" / "events.ndjson"
        )
        self.assertTrue(log_path.exists())
        import json
        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["approved"])

    def test_audit_log_full_logs_everything(self) -> None:
        runner = AgentRunner(AgentConfig(), SandboxConfig())
        ctx = {
            "run_id": "run-full",
            "permission_mode": "bypassPermissions",
            "audit_log": "full",
            "turn": 0,
        }
        self._run_with_ctx(runner, self._make_event(True), ctx)
        self._run_with_ctx(runner, self._make_event(False), ctx)
        log_path = (
            Path(os.environ["HOME"]) / ".clawcodex" / "tool-events" / "run-full" / "events.ndjson"
        )
        self.assertTrue(log_path.exists())
        import json
        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]["approved"])
        self.assertFalse(rows[1]["approved"])

    def test_audit_log_default_is_minimal(self) -> None:
        """When audit_log is not in session_context, default to minimal."""
        runner = AgentRunner(AgentConfig(), SandboxConfig())
        ctx = {
            "run_id": "run-default",
            "permission_mode": "bypassPermissions",
            "turn": 0,
        }
        self._run_with_ctx(runner, self._make_event(True), ctx)
        self._run_with_ctx(runner, self._make_event(False), ctx)
        log_path = (
            Path(os.environ["HOME"]) / ".clawcodex" / "tool-events" / "run-default" / "events.ndjson"
        )
        self.assertTrue(log_path.exists())
        import json
        rows = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["approved"])


class TestPermissionModeAndAuditLogCombination(unittest.TestCase):
    """Ensure old permission_mode values coexist with new audit_log field."""

    def setUp(self) -> None:
        self._home = TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self._home.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self._home.cleanup()

    def test_bypassPermissions_plus_audit_log_full(self) -> None:
        """permission_mode: bypassPermissions + audit_log: full -> all events logged."""
        wf = WorkflowConfig.from_dict({
            "agent": {
                "permission_mode": "bypassPermissions",
                "audit_log": "full",
            }
        })
        self.assertEqual(wf.agent.permission_mode, "bypassPermissions")
        self.assertEqual(wf.agent.audit_log, "full")

        runner = AgentRunner(wf.agent, SandboxConfig())
        event = ToolCallEvent(tool_name="Bash", params={"command": "ls"}, _approved=True)
        ctx = {
            "run_id": "run-combo",
            "permission_mode": wf.agent.permission_mode,
            "audit_log": wf.agent.audit_log,
            "turn": 0,
        }
        runner._append_tool_event_log(event, ctx)
        import json
        log_path = (
            Path(os.environ["HOME"]) / ".clawcodex" / "tool-events" / "run-combo" / "events.ndjson"
        )
        self.assertTrue(log_path.exists())
        rows = [json.loads(l) for l in log_path.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["approved"])


if __name__ == "__main__":
    unittest.main()
