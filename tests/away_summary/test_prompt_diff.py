from __future__ import annotations

from src.agent.conversation import Conversation
from src.types.messages import Message

from clawcodex_ext.away_summary.prompt import (
    AWAY_SUMMARY_INSTRUCTIONS,
    AWAY_SUMMARY_INSTRUCTIONS_AUTO,
    build_summary_messages,
)


def _conv_with_mixed_messages() -> Conversation:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="Please implement the recap feature."),
        Message(role="assistant", content="Sure, working on it now."),
    ]
    return conv


def test_manual_trigger_uses_strict_three_part_template() -> None:
    """``/recap`` (manual) keeps the canonical 1-2 sentence + three-part shape."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="manual",
    )
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert system == AWAY_SUMMARY_INSTRUCTIONS.format(
        language_instruction="MUST write the recap in natural English."
    )
    assert "1-2 plain sentences" in system
    assert "high-level goal" in system.lower()
    assert "current task" in system.lower()
    assert "next action" in system.lower()
    assert "Return only the recap — 1-2 plain sentences, no markdown." in user


def test_auto_trigger_uses_relaxed_three_sentence_template() -> None:
    """The idle "while you were away" card allows 1-3 sentences and
    explicitly invites weaving in session memory when supplied."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="auto",
    )
    system = messages[0]["content"]
    user = messages[1]["content"]

    assert system == AWAY_SUMMARY_INSTRUCTIONS_AUTO.format(
        language_instruction="MUST write the recap in natural English."
    )
    assert "1-3 plain sentences" in system
    assert "60 words" in system.lower()  # relaxed vs manual's 40
    assert "broader session memory" in system.lower()
    # Three-part strict ordering must NOT be required for auto.
    assert "in this order" not in system.lower()


def test_auto_user_prompt_does_not_mention_memory_when_absent() -> None:
    """Without memory the auto user prompt stays simple — no dangling marker."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="auto",
        memory=None,
    )
    user = messages[1]["content"]
    assert "Session memory (broader context)" not in user
    assert "Session transcript:" in user
    assert "1-3 plain sentences" in user


def test_auto_user_prompt_includes_memory_when_provided() -> None:
    """Memory is injected as a separate block the recap can weave in."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="auto",
        memory="Title: Refactor recap\nGoals:\n- align wording",
    )
    user = messages[1]["content"]
    assert "Session memory (broader context):\nTitle: Refactor recap" in user
    assert "Session transcript:" in user
    # Memory is positioned BEFORE the transcript so the model sees the
    # broader context first.
    assert user.index("Session memory") < user.index("Session transcript")


def test_manual_user_prompt_ignores_memory() -> None:
    """``/recap`` is a focused, transcript-only view — memory is dropped."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="manual",
        memory="Title: should-not-appear",
    )
    user = messages[1]["content"]
    assert "Title: should-not-appear" not in user


def test_unknown_trigger_falls_back_to_manual() -> None:
    """Callers that pass an unrecognised trigger get the manual shape,
    matching the docstring's ``"manual"`` default behaviour."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="totally-unknown",
    )
    assert messages[0]["content"] == AWAY_SUMMARY_INSTRUCTIONS.format(
        language_instruction="MUST write the recap in natural English."
    )


def test_chinese_session_uses_chinese_language_instruction() -> None:
    """The relaxed (auto) template still respects the Chinese language gate."""
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="帮我实现 recap 功能"),
        Message(role="assistant", content="好的，我来实现。"),
    ]
    messages = build_summary_messages(conv, max_input_tokens=4_000, trigger="auto")
    system = messages[0]["content"]
    assert "MUST write the recap in natural Simplified Chinese" in system


def test_auto_template_forbids_thinking_preamble() -> None:
    """The relaxed auto template keeps the same anti-CoT guards as manual."""
    messages = build_summary_messages(
        _conv_with_mixed_messages(),
        max_input_tokens=4_000,
        trigger="auto",
    )
    system = messages[0]["content"].lower()
    assert "thinking process" in system
    assert "do not output any internal chain-of-thought" in system
    assert "<think>" in messages[0]["content"]