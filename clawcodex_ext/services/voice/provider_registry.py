"""STT provider registry — F-64 P64-A.

A tiny registry that maps provider names (``"anthropic"`` / ``"doubao"``)
to a *factory* callable producing a :class:`STTProvider` instance. The
factory pattern lets us defer the heavy imports (``websockets`` for
Anthropic, ``doubaoime-asr`` for doubao — both optional) until the user
actually starts a recording, rather than at REPL boot.

Design
------
* :func:`register_stt_provider` — register a factory under a name.
* :func:`get_stt_provider` — instantiate by name (raises ``KeyError`` if
  unknown; the caller maps that to a user-facing "unavailable" message).
* :func:`list_stt_providers` — names of all registered providers, for
  ``/voice help`` and diagnostics.

The registry is process-global (module-level dict) — providers are
stateless factories so sharing across sessions is fine. The Anthropic
factory binds the OAuth token at construction time; the doubao factory
binds the credentials-file path.

This lives in the patch layer (``clawcodex_ext``) so third-party
extensions in ``extensions/`` could register additional STT backends via
the same ``register_stt_provider`` entry point without touching upstream.
"""
from __future__ import annotations

from typing import Callable, Protocol

from .stt import STTProvider

__all__ = [
    "STTProviderFactory",
    "register_stt_provider",
    "get_stt_provider",
    "list_stt_providers",
    "STT_REGISTRY",
]


class STTProviderFactory(Protocol):
    """Callable that constructs a :class:`STTProvider` instance.

    The factory receives no args — any credentials/config it needs are
    read from the environment / settings / credential file at call time,
    so a single registered factory works across sessions. This keeps the
    registry surface trivial and avoids passing auth tokens through it.
    """

    def __call__(self) -> STTProvider: ...


# Process-global: name → factory. Module-level rather than a class so
# import-time registration (the ``_register_builtins`` call below) is a
# simple dict mutation, no singleton ceremony.
STT_REGISTRY: dict[str, STTProviderFactory] = {}


def register_stt_provider(name: str, factory: STTProviderFactory) -> None:
    """Register a STT provider factory under ``name`` (case-insensitive).

    Re-registering an existing name replaces it — useful for tests that
    inject a stub provider. The factories themselves are cheap (just a
    closure capturing nothing) so this isn't a memory concern.
    """
    STT_REGISTRY[name.lower()] = factory


def get_stt_provider(name: str) -> STTProvider:
    """Instantiate the named provider.

    Raises ``KeyError`` if ``name`` isn't registered — callers (the
    push-to-talk controller, ``/voice``) map that to a user-facing
    "backend unavailable, run /voice <provider> to configure" message
    rather than letting it propagate.
    """
    factory = STT_REGISTRY.get(name.lower())
    if factory is None:
        raise KeyError(f"STT provider not registered: {name!r}")
    return factory()


def list_stt_providers() -> list[str]:
    """Names of all registered providers, sorted (for ``/voice help``)."""
    return sorted(STT_REGISTRY)


def _register_builtins() -> None:
    """Register the two built-in providers (Anthropic + Doubao).

    Factories import their provider module lazily so the optional deps
    (``websockets`` / ``doubaoime-asr``) are only imported when the user
    actually selects that backend — not at registry boot. Import failures
    surface as ``ImportError`` from :func:`get_stt_provider`, which the
    push-to-talk controller translates to a clear "install X to use this
    backend" message.
    """
    # Anthropic — always registered; the factory only fails at connect
    # time if OAuth is missing (handled inside the provider).
    def _anthropic_factory() -> STTProvider:
        from .anthropic_stt import AnthropicSTTProvider

        return AnthropicSTTProvider()

    # Doubao — registered unconditionally; the factory imports the
    # optional ``doubaoime-asr`` dep and raises ``ImportError`` if absent.
    # This keeps ``list_stt_providers`` honest (both backends always
    # listed) while deferring the dep check to actual use.
    def _doubao_factory() -> STTProvider:
        from .doubao_stt import DoubaoSTTProvider

        return DoubaoSTTProvider()

    register_stt_provider("anthropic", _anthropic_factory)
    register_stt_provider("doubao", _doubao_factory)


_register_builtins()
