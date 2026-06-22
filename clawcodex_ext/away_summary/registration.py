"""Command registration for Away Summary."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.away_summary.command import build_recap_command
from clawcodex_ext.away_summary.config import load_away_summary_config


def register_away_summary_commands(registry: Any | None = None) -> None:
    """Register /recap when enabled.

    This is intentionally separate from the Away Summary service/controller so
    future removal of the slash command can leave automatic summaries intact.
    """

    from src.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    if not load_away_summary_config().recap_command_enabled:
        try:
            reg.unregister("recap")
        except Exception:
            pass
        return

    reg.register(build_recap_command())
