from __future__ import annotations

import json

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.context import IntentForecastContextBuilder


def test_workspace_signals_read_last_command_failures_and_test_mapping(tmp_path) -> None:
    claw = tmp_path / ".clawcodex"
    claw.mkdir()
    (claw / "last_command.json").write_text(
        json.dumps(
            {
                "command": "pytest tests/intent_forecast",
                "exit_code": 1,
                "output": "FAILED tests/intent_forecast/test_service.py::test_x",
            }
        ),
        encoding="utf-8",
    )

    context = IntentForecastContextBuilder(
        conversation=None,
        workspace_root=tmp_path,
        config=IntentForecastConfig(),
        sessions_dir=tmp_path / "sessions",
        feedback_base_dir=tmp_path,
    ).build()

    assert context.workspace["last_command"] == "pytest tests/intent_forecast"
    assert context.workspace["last_command_exit"] == 1
    assert context.workspace["last_test_failures"] == ["FAILED tests/intent_forecast/test_service.py::test_x"]
    assert context.intent_stage == "debug"
