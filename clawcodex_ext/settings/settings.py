"""
Settings bridge — re-exports from canonical ``src.settings.settings``.

This thin module exists so that ``clawcodex_ext.query.query`` (and other
decoupled modules) can keep using ``from clawcodex_ext.settings.settings
import get_settings`` without a direct dependency on ``src.*``.

During a future full migration the authoritative implementation will move
here; until then this re-export shim avoids a broken import.
"""

from src.settings.settings import get_settings, invalidate_settings_cache, load_settings

__all__ = [
    "get_settings",
    "invalidate_settings_cache",
    "load_settings",
]
