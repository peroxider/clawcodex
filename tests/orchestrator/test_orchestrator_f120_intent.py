"""F-120 Step 1: Intent.REBASE + Command.REBASE + 解析 + 优先级合并.

Covers:
  - Intent.REBASE enum 值稳定
  - Command.REBASE enum 值稳定
  - intent_from_label_set 解析 agent:rebase
  - parse_agent_command 解析 /agent rebase
  - command_to_intent 映射 Command.REBASE → Intent.REBASE
  - merge_intents 优先级：BLOCKED > REBASE > FOLLOWUP > RETRY > NONE
  - merge_intents_with_cli 同上 + CLI 优先级最高
  - 自定义 intent_labels（rebase 自定义 key）
"""

from __future__ import annotations

import unittest

from extensions.orchestrator.tracker import (
    DEFAULT_INTENT_LABELS,
    Command,
    Intent,
    command_to_intent,
    intent_from_label_set,
    merge_intents,
    merge_intents_with_cli,
    parse_agent_command,
)


class TestIntentRebaseEnum(unittest.TestCase):
    def test_intent_rebase_value(self) -> None:
        self.assertEqual(Intent.REBASE.value, "rebase")

    def test_command_rebase_value(self) -> None:
        self.assertEqual(Command.REBASE.value, "rebase")

    def test_intent_lookup_by_value(self) -> None:
        self.assertIs(Intent("rebase"), Intent.REBASE)
        self.assertIs(Command("rebase"), Command.REBASE)


class TestIntentFromLabelSetRebase(unittest.TestCase):
    def test_rebase_label_default(self) -> None:
        self.assertIs(
            intent_from_label_set(["agent:rebase"]),
            Intent.REBASE,
        )

    def test_rebase_alongside_retry(self) -> None:
        # REBASE 优先级高于 RETRY（force-push 比 commit 重置更激进）。
        self.assertIs(
            intent_from_label_set(["agent:rebase", "agent:retry"]),
            Intent.REBASE,
        )

    def test_rebase_alongside_followup(self) -> None:
        self.assertIs(
            intent_from_label_set(["agent:rebase", "agent:follow-up"]),
            Intent.REBASE,
        )

    def test_blocked_wins_over_rebase(self) -> None:
        # BLOCKED 仍然是 sticky 最高优先级。
        self.assertIs(
            intent_from_label_set(["agent:rebase", "agent:blocked"]),
            Intent.BLOCKED,
        )

    def test_custom_rebase_label(self) -> None:
        labels = {**DEFAULT_INTENT_LABELS, "rebase": "ops:rebase"}
        self.assertIs(
            intent_from_label_set(["ops:rebase"], labels),
            Intent.REBASE,
        )


class TestParseAgentCommandRebase(unittest.TestCase):
    def test_rebase_command(self) -> None:
        self.assertEqual(parse_agent_command("/agent rebase"), Command.REBASE)

    def test_rebase_command_with_whitespace(self) -> None:
        self.assertEqual(parse_agent_command("/agent   rebase"), Command.REBASE)

    def test_rebase_unknown_command_returns_none(self) -> None:
        # Defensive: unknown command tokens are NOT silently mapped to
        # Command.REBASE.
        self.assertIsNone(parse_agent_command("/agent random"))

    def test_existing_commands_unaffected(self) -> None:
        self.assertEqual(parse_agent_command("/agent retry"), Command.RETRY)
        self.assertEqual(parse_agent_command("/agent follow-up"), Command.FOLLOWUP)
        self.assertEqual(parse_agent_command("/agent unblock"), Command.UNBLOCK)


class TestCommandToIntentRebase(unittest.TestCase):
    def test_rebase_command_maps_to_rebase_intent(self) -> None:
        self.assertIs(command_to_intent(Command.REBASE), Intent.REBASE)

    def test_existing_commands_unaffected(self) -> None:
        self.assertIs(command_to_intent(Command.RETRY), Intent.RETRY)
        self.assertIs(command_to_intent(Command.FOLLOWUP), Intent.FOLLOWUP)
        self.assertIs(command_to_intent(Command.UNBLOCK), Intent.NONE)


class TestMergeIntentsRebase(unittest.TestCase):
    def test_rebase_beats_retry(self) -> None:
        self.assertIs(
            merge_intents(Intent.RETRY, Intent.REBASE),
            Intent.REBASE,
        )

    def test_rebase_beats_followup(self) -> None:
        self.assertIs(
            merge_intents(Intent.FOLLOWUP, Intent.REBASE),
            Intent.REBASE,
        )

    def test_blocked_beats_rebase(self) -> None:
        self.assertIs(
            merge_intents(Intent.REBASE, Intent.BLOCKED),
            Intent.BLOCKED,
        )

    def test_rebase_beats_none(self) -> None:
        self.assertIs(
            merge_intents(Intent.NONE, Intent.REBASE),
            Intent.REBASE,
        )


class TestMergeIntentsWithCliRebase(unittest.TestCase):
    def test_cli_rebase_wins(self) -> None:
        self.assertIs(
            merge_intents_with_cli(
                label_intent=Intent.RETRY,
                command_intent=Intent.NONE,
                cli_intent=Intent.REBASE,
            ),
            Intent.REBASE,
        )

    def test_cli_blocked_beats_rebase(self) -> None:
        self.assertIs(
            merge_intents_with_cli(
                label_intent=Intent.REBASE,
                command_intent=Intent.REBASE,
                cli_intent=Intent.BLOCKED,
            ),
            Intent.BLOCKED,
        )

    def test_label_rebase_beats_comment_retry(self) -> None:
        # REBASE > RETRY so the label REBASE wins.
        self.assertIs(
            merge_intents_with_cli(
                label_intent=Intent.REBASE,
                command_intent=Intent.RETRY,
                cli_intent=Intent.NONE,
            ),
            Intent.REBASE,
        )


if __name__ == "__main__":
    unittest.main()