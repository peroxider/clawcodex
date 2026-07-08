"""Unit tests for the orchestrator tool-call approval policy system.

Covers:

* :class:`ToolCallEvent` allow / deny / is_approved transitions.
* Built-in policies: :class:`NeverApprovalPolicy`,
  :class:`AskApprovalPolicy`, :class:`ApproveSafeOnlyPolicy`.
* The :func:`get_approval_policy` name resolver (str / dict / unknown).
* :func:`build_approval_policy_map` integration with a
  :class:`SandboxConfig`-like object.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from extensions.orchestrator.approval_policy import (
    ApproveSafeOnlyPolicy,
    ApprovalPolicy,
    AskApprovalPolicy,
    NeverApprovalPolicy,
    ToolCallEvent,
    build_approval_policy_map,
    get_approval_policy,
)


# ---------------------------------------------------------------------------
# ToolCallEvent
# ---------------------------------------------------------------------------


class TestToolCallEvent(unittest.TestCase):
    def test_defaults_are_unevaluated(self) -> None:
        event = ToolCallEvent(tool_name="bash")
        self.assertEqual(event.tool_name, "bash")
        self.assertEqual(event.params, {})
        self.assertIsNone(event.tool_use_id)
        self.assertIsNone(event.is_approved)
        self.assertIsNone(event._approved)
        self.assertIsNone(event._deny_reason)

    def test_allow_sets_approved_true(self) -> None:
        event = ToolCallEvent(tool_name="read")
        event.allow()
        self.assertTrue(event.is_approved)
        self.assertIsNone(event._deny_reason)

    def test_allow_with_reason_keeps_reason(self) -> None:
        event = ToolCallEvent(tool_name="read")
        event.allow("policy=never")
        self.assertTrue(event.is_approved)
        self.assertEqual(event._deny_reason, "policy=never")

    def test_deny_sets_approved_false(self) -> None:
        event = ToolCallEvent(tool_name="bash")
        event.deny(reason="nope")
        self.assertFalse(event.is_approved)
        self.assertEqual(event._deny_reason, "nope")

    def test_overwrite_allow_then_deny(self) -> None:
        event = ToolCallEvent(tool_name="x")
        event.allow("first")
        event.deny("second")
        self.assertFalse(event.is_approved)
        self.assertEqual(event._deny_reason, "second")


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------


class TestNeverApprovalPolicy(unittest.TestCase):
    def test_evaluates_true_and_marks_approved(self) -> None:
        policy = NeverApprovalPolicy()
        event = ToolCallEvent(tool_name="bash", params={"cmd": "ls"})
        result = policy.evaluate(event, session_context={})
        self.assertTrue(result)
        self.assertTrue(event.is_approved)
        self.assertEqual(event._deny_reason, "policy=never")


class TestAskApprovalPolicy(unittest.TestCase):
    def test_evaluates_false_and_marks_denied(self) -> None:
        policy = AskApprovalPolicy()
        event = ToolCallEvent(tool_name="bash")
        result = policy.evaluate(event, session_context={})
        self.assertFalse(result)
        self.assertFalse(event.is_approved)
        self.assertIn("policy=ask", event._deny_reason or "")


class TestApproveSafeOnlyPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ApproveSafeOnlyPolicy()

    def _event(self, name: str) -> ToolCallEvent:
        return ToolCallEvent(tool_name=name, params={})

    def test_safe_tools_are_approved(self) -> None:
        for safe in (
            "glob",
            "grep",
            "read",
            "read_multiple_files",
            "web_search",
            "web_fetch",
            "toolsearch",
            "ask_user_question",
        ):
            with self.subTest(tool=safe):
                event = self._event(safe)
                self.assertTrue(self.policy.evaluate(event, {}))
                self.assertTrue(event.is_approved)

    def test_unsafe_tool_is_denied(self) -> None:
        event = self._event("bash")
        self.assertFalse(self.policy.evaluate(event, {}))
        self.assertFalse(event.is_approved)
        self.assertIn("bash", event._deny_reason or "")

    def test_tool_name_is_case_insensitive(self) -> None:
        event = self._event("READ")
        self.assertTrue(self.policy.evaluate(event, {}))
        self.assertTrue(event.is_approved)

    def test_safe_list_includes_canonical_names(self) -> None:
        # Compile-time check on the documented contract.
        self.assertIn("read", ApproveSafeOnlyPolicy._SAFE_TOOLS)
        self.assertIn("web_fetch", ApproveSafeOnlyPolicy._SAFE_TOOLS)


# ---------------------------------------------------------------------------
# get_approval_policy resolver
# ---------------------------------------------------------------------------


class TestGetApprovalPolicy(unittest.TestCase):
    def test_known_name_never(self) -> None:
        policy = get_approval_policy("never")
        self.assertIsInstance(policy, NeverApprovalPolicy)

    def test_known_name_ask(self) -> None:
        policy = get_approval_policy("ask")
        self.assertIsInstance(policy, AskApprovalPolicy)

    def test_known_name_approve_safe_only(self) -> None:
        policy = get_approval_policy("approve-safe-only")
        self.assertIsInstance(policy, ApproveSafeOnlyPolicy)

    def test_name_is_case_and_whitespace_insensitive(self) -> None:
        policy = get_approval_policy("  NEVER  ")
        self.assertIsInstance(policy, NeverApprovalPolicy)

    def test_unknown_name_falls_back_to_never(self) -> None:
        policy = get_approval_policy("definitely-not-a-real-policy")
        self.assertIsInstance(policy, NeverApprovalPolicy)

    def test_dict_config_falls_back_to_never(self) -> None:
        # Inline dict config is treated as auto-approve for safety.
        policy = get_approval_policy({"approval_policy": "ask"})
        self.assertIsInstance(policy, NeverApprovalPolicy)

    def test_empty_dict_falls_back_to_never(self) -> None:
        policy = get_approval_policy({})
        self.assertIsInstance(policy, NeverApprovalPolicy)

    def test_returns_approval_policy_base(self) -> None:
        policy = get_approval_policy("never")
        self.assertIsInstance(policy, ApprovalPolicy)


# ---------------------------------------------------------------------------
# build_approval_policy_map
# ---------------------------------------------------------------------------


class TestBuildApprovalPolicyMap(unittest.TestCase):
    def test_uses_configured_policy_name(self) -> None:
        config = SimpleNamespace(approval_policy="ask")
        mapping = build_approval_policy_map(config)
        self.assertEqual(set(mapping.keys()), {"ask"})
        self.assertIsInstance(mapping["ask"], AskApprovalPolicy)

    def test_defaults_to_never_when_attribute_missing(self) -> None:
        config = SimpleNamespace()  # no approval_policy attribute
        mapping = build_approval_policy_map(config)
        self.assertIn("never", mapping)
        self.assertIsInstance(mapping["never"], NeverApprovalPolicy)

    def test_defaults_to_never_when_none(self) -> None:
        config = SimpleNamespace(approval_policy=None)
        mapping = build_approval_policy_map(config)
        self.assertIn("never", mapping)
        self.assertIsInstance(mapping["never"], NeverApprovalPolicy)

    def test_unknown_policy_maps_to_never(self) -> None:
        config = SimpleNamespace(approval_policy="no-such-policy")
        mapping = build_approval_policy_map(config)
        # Unknown names fall back to NeverApprovalPolicy; the raw key is
        # preserved in the map so callers can detect the substitution.
        self.assertIn("no-such-policy", mapping)
        self.assertIsInstance(mapping["no-such-policy"], NeverApprovalPolicy)


if __name__ == "__main__":
    unittest.main()
