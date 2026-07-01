"""Configuration for Intent Forecast."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntentForecastConfig:
    enabled: bool = True
    idle_seconds: int = 120
    max_sessions: int = 12
    max_transcript_tail_messages: int = 12
    max_input_tokens: int = 16_000
    max_output_tokens: int = 800
    min_confidence: float = 0.45
    auto_display: bool = True
    feedback_enabled: bool = True
    summary_lazy_generate: bool = True

    @classmethod
    def from_mapping(cls, raw: Any) -> "IntentForecastConfig":
        data = raw if isinstance(raw, dict) else {}
        return cls(
            enabled=_bool_value(data.get("enabled"), True),
            idle_seconds=max(1, _int_value(data.get("idle_seconds"), 120)),
            max_sessions=max(0, _int_value(data.get("max_sessions"), 12)),
            max_transcript_tail_messages=max(
                0,
                _int_value(data.get("max_transcript_tail_messages"), 12),
            ),
            max_input_tokens=max(512, _int_value(data.get("max_input_tokens"), 16_000)),
            max_output_tokens=max(64, _int_value(data.get("max_output_tokens"), 800)),
            min_confidence=max(0.0, min(1.0, _float_value(data.get("min_confidence"), 0.45))),
            auto_display=_bool_value(data.get("auto_display"), True),
            feedback_enabled=_bool_value(data.get("feedback_enabled"), True),
            summary_lazy_generate=_bool_value(data.get("summary_lazy_generate"), True),
        )


def load_intent_forecast_config(
    *,
    cwd: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> IntentForecastConfig:
    if overrides is not None:
        return IntentForecastConfig.from_mapping(overrides)
    try:
        from src.settings.settings import load_settings

        settings = load_settings(cwd=cwd)
        raw = getattr(settings, "extra", {}).get("intent_forecast", {})
        return IntentForecastConfig.from_mapping(raw)
    except Exception:
        return IntentForecastConfig()


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
