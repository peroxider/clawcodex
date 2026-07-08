"""Voice subsystem — F-64 Voice Mode.

Provides speech-to-text and voice activity detection, plus the
push-to-talk recording controller and STT provider registry. P64-E
adds the symmetric text-to-speech surface (TTSProvider ABC, OpenAI /
MiniMax / Gemini providers, AudioOutQueue, AudioPlayer).

Layering (F-64):
* Detection + STT abstract base — mirror TS ``voice/`` interfaces.
* :mod:`voice_mode_enabled` — three-layer gate (flag / kill-switch / OAuth).
* :mod:`provider_registry` — STT + TTS backend factory registries.
* :mod:`anthropic_stt` — Anthropic Nova 3 WebSocket streaming (P64-A + P64-C).
* :mod:`doubao_stt` — Doubao ASR AsyncGenerator adapter (P64-A).
* :mod:`minimax_stt` — MiniMax Realtime API STT (P64-D1, voice-in → text-out).
* :mod:`tts` — TTSProvider ABC + TTSConfig + TTSChunk + TTSSynthesis (P64-E1).
* :mod:`openai_tts` — OpenAI audio.speech TTS (P64-E2, reference impl).
* :mod:`minimax_tts` — MiniMax T2A HTTP TTS (P64-E3).
* :mod:`gemini_tts` — Gemini generate_content TTS (P64-E4).
* :mod:`audio_chunk_queue` — push→pull async audio bridge (P64-C, STT side).
* :mod:`audio_out_queue` — bounded async TTS frame queue (P64-E8).
* :mod:`audio_player` — PyAudio / SoX / ffplay PCM player (P64-E8).
* :mod:`audio_recorder` — cross-platform PCM capture (P64-B).
* :mod:`push_to_talk` — recording session orchestrator (P64-B).
"""

from __future__ import annotations

from .audio_chunk_queue import AudioChunkQueue
from .audio_out_queue import AudioOutQueue
from .audio_player import AudioPlayer, has_ffplay, has_pyaudio, has_sox, play_pcm
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
from .minimax_stt import (
    MINIMAX_CREDENTIALS_PATH,
    MINIMAX_REALTIME_ENDPOINTS,
    MiniMaxCredentialsError,
    MiniMaxSTTProvider,
    MiniMaxStreamConnection,
)
from .tts import TTSChunk, TTSConfig, TTSProvider, TTSSynthesis
from .openai_tts import (
    OPENAI_TTS_ENDPOINT,
    OpenAITTSCredentialsError,
    OpenAITTSProvider,
)
from .minimax_tts import (
    MINIMAX_SUPPORTED_MODELS,
    MINIMAX_SYSTEM_VOICES,
    MINIMAX_T2A_ENDPOINTS,
    MINIMAX_TTS_CREDENTIALS_PATH,
    MiniMaxTTSCredentialsError,
    MiniMaxTTSProvider,
)
from .gemini_tts import (
    GEMINI_TTS_DEFAULT_MODEL,
    GEMINI_TTS_DEFAULT_VOICE,
    GeminiTTSCredentialsError,
    GeminiTTSProvider,
)
from .provider_registry import (
    STT_REGISTRY,
    STTProviderFactory,
    TTS_REGISTRY,
    TTSProviderFactory,
    get_stt_provider,
    get_tts_provider,
    list_stt_providers,
    list_tts_providers,
    register_stt_provider,
    register_tts_provider,
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
    # Provider registries (STT + TTS)
    "STT_REGISTRY",
    "STTProviderFactory",
    "TTS_REGISTRY",
    "TTSProviderFactory",
    "get_stt_provider",
    "get_tts_provider",
    "list_stt_providers",
    "list_tts_providers",
    "register_stt_provider",
    "register_tts_provider",
    # Anthropic STT backend
    "ANTHROPIC_VOICE_ENDPOINT",
    "AnthropicSTTProvider",
    "VoiceAuthError",
    "VoiceStreamConnection",
    # Doubao STT backend
    "DOUBAO_CREDENTIALS_PATH",
    "DoubaoCredentialsError",
    "DoubaoSTTProvider",
    "DoubaoStreamConnection",
    # MiniMax STT backend (P64-D1)
    "MINIMAX_CREDENTIALS_PATH",
    "MINIMAX_REALTIME_ENDPOINTS",
    "MiniMaxCredentialsError",
    "MiniMaxSTTProvider",
    "MiniMaxStreamConnection",
    # TTS abstraction (P64-E1)
    "TTSChunk",
    "TTSConfig",
    "TTSProvider",
    "TTSSynthesis",
    # TTS providers (P64-E2/E3/E4)
    "OPENAI_TTS_ENDPOINT",
    "OpenAITTSCredentialsError",
    "OpenAITTSProvider",
    "MINIMAX_SUPPORTED_MODELS",
    "MINIMAX_SYSTEM_VOICES",
    "MINIMAX_T2A_ENDPOINTS",
    "MINIMAX_TTS_CREDENTIALS_PATH",
    "MiniMaxTTSCredentialsError",
    "MiniMaxTTSProvider",
    "GEMINI_TTS_DEFAULT_MODEL",
    "GEMINI_TTS_DEFAULT_VOICE",
    "GeminiTTSCredentialsError",
    "GeminiTTSProvider",
    # Audio pipeline (STT in + TTS out)
    "AudioChunkQueue",
    "AudioOutQueue",
    "AudioPlayer",
    "AudioRecorder",
    "PyAudioRecorder",
    "SoXRecorder",
    "has_ffplay",
    "has_pyaudio",
    "has_sox",
    "make_recorder",
    "play_pcm",
    # Push-to-talk orchestrator
    "PushToTalkController",
    "VoiceSessionResult",
    "VoiceSessionState",
]
