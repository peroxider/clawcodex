"""Command registration for Intent Forecast."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.intent_forecast.command import build_forecast_command


def register_intent_forecast_commands(registry: Any | None = None) -> None:
    from src.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    reg.register(build_forecast_command())
