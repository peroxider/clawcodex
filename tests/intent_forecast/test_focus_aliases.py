from __future__ import annotations

from clawcodex_ext.intent_forecast.focus import compute_workspace_focuses


def test_weak_forecast_text_does_not_force_intent_forecast_focus() -> None:
    focuses = compute_workspace_focuses(
        changed_files=["README.md"],
        recent_messages=[{"role": "user", "content": "forecast the next release risks"}],
    )

    assert all(item["id"] != "intent_forecast" for item in focuses)


def test_intent_forecast_path_is_strong_focus() -> None:
    focuses = compute_workspace_focuses(
        changed_files=["clawcodex_ext/intent_forecast/service.py"],
        recent_messages=[],
    )

    assert focuses[0]["id"] == "intent_forecast"
    assert focuses[0]["confidence"] >= 1.0


def test_cross_module_changes_keep_multiple_focuses() -> None:
    focuses = compute_workspace_focuses(
        changed_files=[
            "clawcodex_ext/intent_forecast/service.py",
            "clawcodex_ext/tui/app.py",
        ],
        recent_messages=[],
    )

    assert {item["id"] for item in focuses} == {"intent_forecast", "tui"}
