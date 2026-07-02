"""Voice subsystem — F-64 Voice Mode.

Provides speech-to-text and voice activity detection, plus the
push-to-talk recording controller and STT provider registry.

Layering (F-64):
* Detection + STT abstract base — mirror TS ``voice/`` interfaces.
* :mod:`voice_mode_enabled` — three-layer gate (flag / kill-switch / OAuth).
* :mod:`provider_registry` — STT backend factory registry.
* :mod:`anthropic_stt` — Anthropic Nova 3 WebSocket streaming (P64-A + P64-C).
* :mod:`doubao_stt` — Doubao ASR AsyncGenerator adapter (P64-A).
* :mod:`audio_chunk_queue` — push→pull async audio bridge (P64-C).
* :mod:`audio_recorder` — cross-platform PCM capture (P64-B).
* :mod:`push_to_talk` — recording session orchestrator (P64-B).
"""
from __future__ import annotations

from .audio_chunk_queue import AudioChunkQueue
from .audio_recorder import (
    AudioRecorder,
    PyAudioRecorder,
    SoXRecorder,
    make_recorder,
)
from .detection import (
    VoiceActivityConfig,
    VoiceActivityDetector,
    VoiceActivityState,
)
from .doubao_stt import (
    DOUBAO_CREDENTIALS_PATH,
    DoubaoCredentialsError,
    DoubaoSTTProvider,
    DoubaoStreamConnection,
)
from .anthropic_stt import (
    ANTHROPIC_VOICE_ENDPOINT,
    AnthropicSTTProvider,
    VoiceAuthError,
    VoiceStreamConnection,
)
from .provider_registry import (
    STT_REGISTRY,
    STTProviderFactory,
    get_stt_provider,
    list_stt_providers,
    register_stt_provider,
)
from .push_to_talk import (
    PushToTalkController,
    VoiceSessionResult,
    VoiceSessionState,
)
from .stt import STTConfig, STTProvider, STTResult
from .voice_mode_enabled import (
    VOICE_PROVIDERS,
    VoiceProvider,
    get_voice_provider,
    has_voice_auth,
    is_voice_available,
    is_voice_disabled_by_kill_switch,
    is_voice_enabled,
    is_voice_feature_enabled,
    is_voice_mode_enabled,
)

__all__ = [
    # Detection + STT base
    "STTConfig",
    "STTProvider",
    "STTResult",
    "VoiceActivityConfig",
    "VoiceActivityDetector",
    "VoiceActivityState",
    # Voice-mode gating
    "VOICE_PROVIDERS",
    "VoiceProvider",
    "get_voice_provider",
    "has_voice_auth",
    "is_voice_available",
    "is_voice_disabled_by_kill_switch",
    "is_voice_enabled",
    "is_voice_feature_enabled",
    "is_voice_mode_enabled",
    # Provider registry
    "STT_REGISTRY",
    "STTProviderFactory",
    "get_stt_provider",
    "list_stt_providers",
    "register_stt_provider",
    # Anthropic backend
    "ANTHROPIC_VOICE_ENDPOINT",
    "AnthropicSTTProvider",
    "VoiceAuthError",
    "VoiceStreamConnection",
    # Doubao backend
    "DOUBAO_CREDENTIALS_PATH",
    "DoubaoCredentialsError",
    "DoubaoSTTProvider",
    "DoubaoStreamConnection",
    # Audio pipeline
    "AudioChunkQueue",
    "AudioRecorder",
    "PyAudioRecorder",
    "SoXRecorder",
    "make_recorder",
    # Push-to-talk orchestrator
    "PushToTalkController",
    "VoiceSessionResult",
    "VoiceSessionState",
]
