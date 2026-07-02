"""STT + TTS provider registries — F-64 P64-A / P64-E7.

Two parallel registries that map provider names to *factory* callables
producing :class:`STTProvider` / :class:`TTSProvider` instances. The
factory pattern lets us defer heavy imports (``websockets`` for
Anthropic/MiniMax, ``doubaoime-asr`` for doubao, ``google-genai`` for
Gemini — all optional) until the user actually starts a recording or
synthesis, rather than at REPL boot.

This lives in the patch layer (``clawcodex_ext``) so third-party
extensions in ``extensions/`` could register additional STT/TTS backends
via the same entry points without touching upstream.
"""
from __future__ import annotations

from typing import Protocol

from .stt import STTProvider
from .tts import TTSProvider

__all__ = [
    "STTProviderFactory",
    "TTSProviderFactory",
    "register_stt_provider",
    "register_tts_provider",
    "get_stt_provider",
    "get_tts_provider",
    "list_stt_providers",
    "list_tts_providers",
    "STT_REGISTRY",
    "TTS_REGISTRY",
]


class STTProviderFactory(Protocol):
    def __call__(self) -> STTProvider: ...


class TTSProviderFactory(Protocol):
    def __call__(self) -> TTSProvider: ...


STT_REGISTRY: dict[str, STTProviderFactory] = {}
TTS_REGISTRY: dict[str, TTSProviderFactory] = {}


def register_stt_provider(name: str, factory: STTProviderFactory) -> None:
    STT_REGISTRY[name.lower()] = factory


def register_tts_provider(name: str, factory: TTSProviderFactory) -> None:
    TTS_REGISTRY[name.lower()] = factory


def get_stt_provider(name: str) -> STTProvider:
    factory = STT_REGISTRY.get(name.lower())
    if factory is None:
        raise KeyError(f"STT provider not registered: {name!r}")
    return factory()


def get_tts_provider(name: str) -> TTSProvider:
    factory = TTS_REGISTRY.get(name.lower())
    if factory is None:
        raise KeyError(f"TTS provider not registered: {name!r}")
    return factory()


def list_stt_providers() -> list[str]:
    return sorted(STT_REGISTRY)


def list_tts_providers() -> list[str]:
    return sorted(TTS_REGISTRY)


def _register_builtins() -> None:
    # STT factories
    def _anthropic_factory() -> STTProvider:
        from .anthropic_stt import AnthropicSTTProvider
        return AnthropicSTTProvider()

    def _doubao_factory() -> STTProvider:
        from .doubao_stt import DoubaoSTTProvider
        return DoubaoSTTProvider()

    def _minimax_factory() -> STTProvider:
        from .minimax_stt import MiniMaxSTTProvider
        return MiniMaxSTTProvider()

    register_stt_provider("anthropic", _anthropic_factory)
    register_stt_provider("doubao", _doubao_factory)
    register_stt_provider("minimax", _minimax_factory)

    # TTS factories (P64-E7)
    def _openai_tts_factory() -> TTSProvider:
        from .openai_tts import OpenAITTSProvider
        return OpenAITTSProvider()

    def _minimax_tts_factory() -> TTSProvider:
        from .minimax_tts import MiniMaxTTSProvider
        return MiniMaxTTSProvider()

    def _gemini_tts_factory() -> TTSProvider:
        from .gemini_tts import GeminiTTSProvider
        return GeminiTTSProvider()

    register_tts_provider("openai", _openai_tts_factory)
    register_tts_provider("minimax", _minimax_tts_factory)
    register_tts_provider("gemini", _gemini_tts_factory)


_register_builtins()
