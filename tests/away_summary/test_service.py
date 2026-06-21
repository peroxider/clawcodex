from __future__ import annotations

from src.agent.conversation import Conversation
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.types.content_blocks import TextBlock
from src.types.messages import Message, normalize_messages_for_api

from clawcodex_ext.away_summary.config import AwaySummaryConfig
from clawcodex_ext.away_summary.fingerprint import last_away_summary_fingerprint
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
    assert "Last assistant response: 你好！看起来我们刚打过招呼。" in result.summary
    assert "TextBlock(" not in result.summary
    assert "type='text'" not in result.summary
