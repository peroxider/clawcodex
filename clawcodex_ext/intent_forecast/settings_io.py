"""Small settings writer for ``settings.intent_forecast``."""

from __future__ import annotations

from typing import Any


def update_intent_forecast_settings(updates: dict[str, Any]) -> None:
    """Persist Intent Forecast settings to the user/global config.

    The settings loader reads extension settings from the nested
    ``settings`` section in ``~/.clawcodex/config.json``. Keep this writer
    intentionally narrow so ``/forecast on|off`` does not serialize merged
    project/local config back into the global file.
    """

    from src.config import _get_default_manager
    from src.settings.settings import invalidate_settings_cache

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    settings = cfg.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    section = settings.get("intent_forecast")
    if not isinstance(section, dict):
        section = {}
    section.update(updates)
    settings["intent_forecast"] = section
    cfg["settings"] = settings
    mgr.save_global(cfg)
    invalidate_settings_cache()
