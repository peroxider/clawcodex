"""Facade — services/voice/__init__.py has been moved to clawcodex_ext.

Real implementations live in ``clawcodex_ext.services.voice``.  Existing
``from src.services.voice import …`` call sites continue to work during
the migration.  New code should import from
``clawcodex_ext.services.voice`` directly.
"""

from clawcodex_ext.services.voice import (  # noqa: F401
    STTConfig,
    STTProvider,
    STTResult,
    VoiceActivityConfig,
    VoiceActivityDetector,
    VoiceActivityState,
)

__all__ = [
    "STTConfig",
    "STTProvider",
    "STTResult",
    "VoiceActivityConfig",
    "VoiceActivityDetector",
    "VoiceActivityState",
]
