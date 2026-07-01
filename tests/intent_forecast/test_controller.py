from __future__ import annotations

from src.agent.conversation import Conversation
from src.types.messages import Message

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.controller import IntentForecastController


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


def _conversation() -> Conversation:
    conv = Conversation()
    conv.messages = [Message(role="user", content="implement forecast")]
    return conv


def test_controller_arms_on_mount_and_fires(tmp_path) -> None:
    timers = FakeTimerFactory()
    displayed = []
    controller = IntentForecastController(
        provider_getter=lambda: None,
        model_getter=lambda: None,
        session_getter=lambda: None,
        workspace_root=tmp_path,
        display=displayed.append,
        config_loader=lambda: IntentForecastConfig(idle_seconds=7),
        conversation_getter=_conversation,
        timer_factory=timers,
    )

    controller.on_mount()
    assert timers.seconds == [7]

    timers.timers[0].fire()
    assert displayed
    assert displayed[0].generated is True


def test_user_interaction_cancels_timer(tmp_path) -> None:
    timers = FakeTimerFactory()
    displayed = []
    controller = IntentForecastController(
        provider_getter=lambda: None,
        model_getter=lambda: None,
        session_getter=lambda: None,
        workspace_root=tmp_path,
        display=displayed.append,
        config_loader=lambda: IntentForecastConfig(idle_seconds=1),
        conversation_getter=_conversation,
        timer_factory=timers,
    )

    controller.on_mount()
    controller.on_user_interaction("typing")
    timers.timers[0].fire()
    assert displayed == []


def test_stale_generation_is_discarded(tmp_path) -> None:
    class Provider:
        def chat(self, **kwargs):
            controller.on_user_interaction("during-provider")

            class Response:
                content = '{"suggestions":[{"title":"x","prompt":"do x","confidence":0.9}]}'

            return Response()

    timers = FakeTimerFactory()
    displayed = []
    controller = IntentForecastController(
        provider_getter=lambda: Provider(),
        model_getter=lambda: "fake",
        session_getter=lambda: None,
        workspace_root=tmp_path,
        display=displayed.append,
        config_loader=lambda: IntentForecastConfig(idle_seconds=1, feedback_enabled=False),
        conversation_getter=_conversation,
        timer_factory=timers,
    )
    controller.on_mount()
    timers.timers[0].fire()
    assert displayed == []


def test_accept_submits_last_result(tmp_path) -> None:
    submitted: list[str] = []
    controller = IntentForecastController(
        provider_getter=lambda: None,
        model_getter=lambda: None,
        session_getter=lambda: None,
        workspace_root=tmp_path,
        display=lambda result: None,
        submit=submitted.append,
        config_loader=lambda: IntentForecastConfig(feedback_enabled=False),
        conversation_getter=_conversation,
        timer_factory=FakeTimerFactory(),
    )
    controller.on_mount()
    controller._timer.fire()  # type: ignore[union-attr]

    assert controller.accept(1) is True
    assert submitted
