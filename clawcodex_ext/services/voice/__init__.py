"""Voice subsystem.

Provides speech-to-text and voice activity detection.
Mirrors TypeScript voice/ directory.
"""

from __future__ import annotations

from .stt import STTConfig, STTProvider, STTResult
from .detection import VoiceActivityConfig, VoiceActivityDetector, VoiceActivityState

__all__ = [
    "STTConfig",
    "STTProvider",
    "STTResult",
    "VoiceActivityConfig",
    "VoiceActivityDetector",
    "VoiceActivityState",
]
