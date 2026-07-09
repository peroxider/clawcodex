"""F-108 P108-G — auto-recovery strategy catalogue tests."""

from __future__ import annotations

import unittest

from clawcodex_ext.diagnostics import (
    RecoveryAction,
    RecoverySpec,
    describe,
    recovery_actions,
)


class TestRecoveryTable(unittest.TestCase):
    def test_five_paths_match_plan(self):
        actions = {spec.action for spec in recovery_actions()}
        # F-108 §十八 P108-G promises these five:
        self.assertIn(RecoveryAction.PERMISSION_AUTO_DENY, actions)
        self.assertIn(RecoveryAction.ASK_USER_EMPTY, actions)
        self.assertIn(RecoveryAction.LLM_TURN_TIMEOUT, actions)
        self.assertIn(RecoveryAction.TOOL_TIMEOUT, actions)
        self.assertIn(RecoveryAction.AGENT_LOOP_TIMEOUT, actions)
        self.assertEqual(len(actions), 5)

    def test_describe_returns_spec(self):
        spec = describe(RecoveryAction.PERMISSION_AUTO_DENY)
        self.assertIsInstance(spec, RecoverySpec)
        self.assertEqual(spec.action, RecoveryAction.PERMISSION_AUTO_DENY)
        self.assertIn("agent_bridge", spec.integration_point)

    def test_describe_raises_for_unknown(self):
        # RecoveryAction is an Enum so we can't construct an unknown
        # value; ensure the str-based path raises for an invalid
        # value via enum_value coercion.
        with self.assertRaises(KeyError):
            describe("not_a_real_action")  # type: ignore[arg-type]

    def test_user_perception_strings_have_chinese_or_arrows(self):
        # Loose check — the plan categorised each path with a Chinese
        # perception phrase or a short English tag. Pin that we never
        # surfaced an empty user-perception string after a refactor.
        for spec in recovery_actions():
            self.assertTrue(spec.user_perception, f"{spec.action} missing perception")
            self.assertTrue(spec.mechanism, f"{spec.action} missing mechanism")
            self.assertTrue(spec.integration_point, f"{spec.action} missing integration_point")


if __name__ == "__main__":
    unittest.main()
