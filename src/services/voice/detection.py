"""Facade — services/voice/detection.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.voice.detection``.
Existing ``from src.services.voice.detection import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.voice.detection`` directly.
"""

from clawcodex_ext.services.voice.detection import (  # noqa: F401
    VoiceActivityConfig,
    VoiceActivityDetector,
    VoiceActivityState,
)

__all__ = [
    "VoiceActivityConfig",
    "VoiceActivityDetector",
    "VoiceActivityState",
]
