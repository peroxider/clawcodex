from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from clawcodex_ext.intent_forecast.command import _forecast_call
from clawcodex_ext.intent_forecast.messages import ForecastResult, ForecastSuggestion


class FakeController:
    def __init__(self) -> None:
        self.last_result = ForecastResult(
            generated=True,
            fingerprint="fp",
            suggestions=[
                ForecastSuggestion(
                    id="s1",
                    title="Do one",
                    prompt="do one",
                    confidence=0.8,
                )
            ],
        )
        self.dismissed = False

    def dismiss(self) -> None:
        self.dismissed = True


def test_forecast_accept_uses_controller_last_result(tmp_path: Path) -> None:
    ctx = SimpleNamespace(cwd=tmp_path, intent_forecast_controller=FakeController())

    result = _forecast_call("accept 1", ctx)

    assert result.type == "prompt"
    assert result.value == "do one"


def test_forecast_dismiss_uses_controller(tmp_path: Path) -> None:
    controller = FakeController()
    ctx = SimpleNamespace(cwd=tmp_path, intent_forecast_controller=controller)

    result = _forecast_call("dismiss", ctx)

    assert result.value == "Forecast dismissed."
    assert controller.dismissed is True
