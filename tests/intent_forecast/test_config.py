from __future__ import annotations

from clawcodex_ext.intent_forecast.config import IntentForecastConfig


def test_config_defaults() -> None:
    cfg = IntentForecastConfig()
    assert cfg.enabled is True
    assert cfg.idle_seconds == 120
    assert cfg.max_sessions == 12
    assert cfg.response_language == "auto"


def test_config_from_mapping_clamps_values() -> None:
    cfg = IntentForecastConfig.from_mapping(
        {
            "enabled": "off",
            "idle_seconds": 0,
            "min_confidence": 2,
            "feedback_enabled": "false",
        }
    )
    assert cfg.enabled is False
    assert cfg.idle_seconds == 1
    assert cfg.min_confidence == 1.0
    assert cfg.feedback_enabled is False


def test_config_response_language_override() -> None:
    assert IntentForecastConfig.from_mapping({"response_language": "zh-CN"}).response_language == "Chinese"
    assert IntentForecastConfig.from_mapping({"response_language": "english"}).response_language == "English"
    assert IntentForecastConfig.from_mapping({"response_language": "klingon"}).response_language == "auto"
