from __future__ import annotations

from clawcodex_ext.intent_forecast.cli import (
    _last_cli_result_path,
    _save_last_cli_result,
)
from clawcodex_ext.intent_forecast.cli import run_forecast_command
from clawcodex_ext.intent_forecast.messages import ForecastResult, ForecastSuggestion


def test_cli_status_json(capsys) -> None:
    rc = run_forecast_command(["status", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"idle_seconds": 120' in out


def test_cli_process_pending(capsys) -> None:
    rc = run_forecast_command(["summarize", "--pending", "--json"])
    assert rc == 0
    assert '"processed"' in capsys.readouterr().out


def test_cli_accept_saved_result(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    _save_last_cli_result(
        ForecastResult(
            generated=True,
            suggestions=[
                ForecastSuggestion(id="s1", title="A", prompt="do saved", confidence=0.8)
            ],
        )
    )

    rc = run_forecast_command(["accept", "s1"])

    assert rc == 0
    assert "do saved" in capsys.readouterr().out
    assert not _last_cli_result_path().exists()
