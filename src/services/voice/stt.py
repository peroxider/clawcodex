"""Facade — services/voice/stt.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.voice.stt``.
Existing ``from src.services.voice.stt import …`` call sites continue
to work during the migration.  New code should import from
``clawcodex_ext.services.voice.stt`` directly.
"""

from clawcodex_ext.services.voice.stt import (  # noqa: F401
    STTConfig,
    STTProvider,
    STTResult,
)

__all__ = [
    "STTConfig",
    "STTProvider",
    "STTResult",
]
