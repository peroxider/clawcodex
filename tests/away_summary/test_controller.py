from __future__ import annotations

from src.agent.conversation import Conversation
from clawcodex_ext.providers.base import ChatResponse
from src.types.messages import Message

from clawcodex_ext.away_summary.config import AwaySummaryConfig
from clawcodex_ext.away_summary.controller import AwaySummaryController
from clawcodex_ext.away_summary.fingerprint import conversation_fingerprint
from clawcodex_ext.away_summary.messages import create_away_summary_message


class FakeTimer:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class FakeTimerFactory:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []
        self.seconds: list[float] = []

    def call_later(self, seconds: float, callback):
        self.seconds.append(seconds)
        timer = FakeTimer(callback)
        self.timers.append(timer)
        return timer


class FakeProvider:
    model = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return ChatResponse(content="auto recap", model="fake", usage={}, finish_reason="stop")


class FakeSession:
    session_id = "s1"

    def save(self) -> None:
        return None


def _conversation() -> Conversation:
    conv = Conversation()
    conv.messages = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="hi"),
    ]
    return conv


def test_controller_arms_after_assistant_turn_and_fires() -> None:
    conv = _conversation()
    timers = FakeTimerFactory()
    provider = FakeProvider()
    displayed: list[str] = []
    controller = AwaySummaryController(
        conversation=conv,
        provider_getter=lambda: provider,
        model_getter=lambda: "fake",
        session_getter=lambda: FakeSession(),
        display=displayed.append,
        config_loader=lambda: AwaySummaryConfig(idle_seconds=180),
        timer_factory=timers,
    )

    controller.on_assistant_turn_complete()
    assert timers.seconds == [180]

    timers.timers[0].fire()
    assert provider.calls == 1
    assert displayed and "auto recap" in displayed[0]
    assert conv.messages[-1].subtype == "away_summary"


def test_user_interaction_cancels_timer() -> None:
    timers = FakeTimerFactory()
    provider = FakeProvider()
    controller = AwaySummaryController(
        conversation=_conversation(),
        provider_getter=lambda: provider,
        model_getter=lambda: "fake",
        session_getter=lambda: None,
        config_loader=lambda: AwaySummaryConfig(idle_seconds=5),
        timer_factory=timers,
    )

    controller.on_assistant_turn_complete()
    controller.on_user_interaction()
    timers.timers[0].fire()
    assert provider.calls == 0


def test_disabled_auto_summary_does_not_arm() -> None:
    timers = FakeTimerFactory()
    controller = AwaySummaryController(
        conversation=_conversation(),
        provider_getter=lambda: FakeProvider(),
        model_getter=lambda: "fake",
        session_getter=lambda: None,
        config_loader=lambda: AwaySummaryConfig(enabled=False),
        timer_factory=timers,
    )

    controller.on_assistant_turn_complete()
    assert timers.timers == []


def test_manual_recap_suppresses_auto_recap_for_same_content() -> None:
    conv = _conversation()
    conv.messages.append(
        create_away_summary_message(
            "manual recap",
            trigger="manual",
            fingerprint=conversation_fingerprint(conv),
            message_count=len(conv.messages),
            model="fake",
        )
    )
    timers = FakeTimerFactory()
    provider = FakeProvider()
    controller = AwaySummaryController(
        conversation=conv,
        provider_getter=lambda: provider,
        model_getter=lambda: "fake",
        session_getter=lambda: FakeSession(),
        config_loader=lambda: AwaySummaryConfig(idle_seconds=1),
        timer_factory=timers,
    )

    controller.on_assistant_turn_complete()
    assert timers.seconds == []
    assert provider.calls == 0
    assert conv.messages[-1]._away_summary_meta["trigger"] == "manual"


def test_auto_failure_is_swallowed(caplog) -> None:
    timers = FakeTimerFactory()
    controller = AwaySummaryController(
        conversation=_conversation(),
        provider_getter=lambda: FakeProvider(fail=True),
        model_getter=lambda: "fake",
        session_getter=lambda: FakeSession(),
        config_loader=lambda: AwaySummaryConfig(idle_seconds=1),
        timer_factory=timers,
    )

    controller.on_assistant_turn_complete()
    timers.timers[0].fire()
    assert "Away Summary failed" in caplog.text
