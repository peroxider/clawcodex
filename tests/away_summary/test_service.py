from __future__ import annotations

from src.agent.conversation import Conversation
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.types.content_blocks import TextBlock
from src.types.messages import Message, normalize_messages_for_api

from clawcodex_ext.away_summary.config import AwaySummaryConfig
from clawcodex_ext.away_summary.fingerprint import last_away_summary_fingerprint
from clawcodex_ext.away_summary.prompt import (
    build_summary_messages,
    infer_response_language,
)
from clawcodex_ext.away_summary.service import AwaySummaryService


class FakeProvider:
    def __init__(self, content: str = "worked on the feature") -> None:
        self.content = content
        self.calls: list[dict] = []
        self.model = "fake-model"

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return ChatResponse(
            content=self.content,
            model="fake-model",
            usage={},
            finish_reason="stop",
        )


class FakeSession:
    session_id = "session-1"

    def __init__(self) -> None:
        self.saved = 0

    def save(self) -> None:
        self.saved += 1


def _conversation() -> Conversation:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="please implement recap"),
        Message(role="assistant", content="I will do that"),
    ]
    return conv


def test_service_generates_and_persists_system_message() -> None:
    conv = _conversation()
    provider = FakeProvider("Summary bullet")
    session = FakeSession()

    result = AwaySummaryService(
        conversation=conv,
        provider=provider,
        model="fake-model",
        session=session,
        config=AwaySummaryConfig(),
    ).generate(trigger="manual")

    assert result.generated is True
    assert "Summary bullet" in result.summary
    assert conv.messages[-1].role == "system"
    assert conv.messages[-1].subtype == "away_summary"
    assert session.saved == 1
    assert provider.calls[0]["tools"] is None


def test_away_summary_does_not_enter_api_messages() -> None:
    conv = _conversation()
    AwaySummaryService(
        conversation=conv,
        provider=FakeProvider(),
        model="fake-model",
        config=AwaySummaryConfig(),
    ).generate(trigger="manual")

    api_messages = normalize_messages_for_api(conv.messages)
    assert all("[AWAY SUMMARY]" not in str(m.get("content")) for m in api_messages)


def test_service_suppresses_duplicate_content() -> None:
    conv = _conversation()
    service = AwaySummaryService(
        conversation=conv,
        provider=FakeProvider(),
        model="fake-model",
        config=AwaySummaryConfig(),
    )
    first = service.generate(trigger="manual")
    second = service.generate(trigger="manual")

    assert first.generated is True
    assert second.generated is False
    assert "No new session content" in second.reason
    assert last_away_summary_fingerprint(conv) == first.fingerprint


def test_service_suppresses_duplicate_content_across_triggers() -> None:
    conv = _conversation()
    service = AwaySummaryService(
        conversation=conv,
        provider=FakeProvider(),
        model="fake-model",
        config=AwaySummaryConfig(),
    )
    first = service.generate(trigger="manual")
    second = service.generate(trigger="auto")

    assert first.generated is True
    assert second.generated is False
    assert "No new session content" in second.reason
    assert conv.messages[-1]._away_summary_meta["trigger"] == "manual"


def test_service_min_turns_threshold() -> None:
    conv = Conversation()
    conv.messages = [Message(role="user", content="hello")]

    result = AwaySummaryService(
        conversation=conv,
        provider=FakeProvider(),
        model="fake-model",
        config=AwaySummaryConfig(min_turns=1),
    ).generate(trigger="manual")

    assert result.generated is False
    assert "Not enough conversation" in result.reason


def test_fallback_summary_flattens_content_blocks() -> None:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="你好"),
        Message(role="assistant", content=[TextBlock(text="你好！看起来我们刚打过招呼。")]),
    ]

    result = AwaySummaryService(
        conversation=conv,
        provider=FakeProvider(""),
        model="fake-model",
        config=AwaySummaryConfig(),
    ).generate(trigger="auto")

    assert result.generated is True
    assert "Started with: 你好" in result.summary
    assert "TextBlock(" not in result.summary
    assert "type='text'" not in result.summary


def test_infer_language_from_chinese_user_message() -> None:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="请实现一个递归函数"),
        Message(role="assistant", content="好的，以下是递归函数的实现。"),
    ]
    assert infer_response_language(conv) == "Chinese"


def test_infer_language_falls_back_to_assistant_when_user_is_code_heavy() -> None:
    """User turns dominated by English identifiers should not drown out Chinese intent."""
    conv = Conversation()
    conv.messages = [
        Message(
            role="user",
            content="clawcodex_ext/away_summary/prompt.py 的 infer_response_language 改成中文",
        ),
        Message(role="assistant", content="已修改。现在函数会正确检测中文。"),
    ]
    assert infer_response_language(conv) == "Chinese"


def test_infer_language_english_conversation() -> None:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="fix bug in test_service.py"),
        Message(role="assistant", content="Fixed the bug in test_service.py."),
    ]
    assert infer_response_language(conv) == "English"


def test_infer_language_explicit_override() -> None:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="fix bug in test_service.py"),
        Message(role="assistant", content="Fixed the bug in test_service.py."),
    ]
    assert infer_response_language(conv, explicit="Chinese") == "Chinese"
    assert infer_response_language(conv, explicit="English") == "English"


def test_summary_prompt_includes_must_language_instruction() -> None:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="请帮我修改代码"),
        Message(role="assistant", content="好的，我来帮你。"),
    ]
    prompt = build_summary_messages(conv, max_input_tokens=4_000)[0]["content"]
    assert "MUST write the recap in natural Simplified Chinese" in prompt
    assert "MUST be written in the language specified above" in prompt
    assert "Do not switch languages mid-recap" in prompt
