"""Downstream provider extensions — model discovery hooks and provider overrides."""

from __future__ import annotations

# Note: ``register_provider`` and ``register_provider_info`` are safe to call
# at module level because they only touch the PROVIDER_INFO dict and the
# _EXTRA_PROVIDER_CLASSES dict — they do NOT import any provider class
# immediately (avoiding the circular-import chain:
#   src.auth.codex_oauth → clawcodex_ext → … → src.auth.codex_oauth).

from src.providers import PROVIDER_INFO

from clawcodex_ext.providers.factory import register_provider, register_provider_info

from clawcodex_ext.providers.hooks import _codex_api_discovery
from clawcodex_ext.cli.model_cmd.registry import register_discovery_hook

register_discovery_hook("openai-codex", _codex_api_discovery)


def _OpenAICodexProvider_lazy():
    """Lazy accessor that defers the import until first use.

    We cannot import OpenAICodexProvider at module level because it
    depends on src.auth.codex_oauth which may trigger a circular import.
    Instead, register a callable that returns the class on demand.
    """
    from clawcodex_ext.providers.openai_codex_provider import OpenAICodexProvider

    return OpenAICodexProvider


# Register openai-codex provider info via the generic extension API
# rather than hardcoding it in src/providers/__init__.py.
# Use register_provider (not just register_provider_info) so that
# get_provider_class("openai-codex") also works via _EXTRA_PROVIDER_CLASSES.
register_provider(
    "openai-codex",
    {
        "label": "OpenAI Codex (ChatGPT OAuth)",
        "default_base_url": "https://chatgpt.com/backend-api/codex",
        "default_model": "gpt-5.3-codex",
        "available_models": [
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
        ],
    },
    _OpenAICodexProvider_lazy,  # type: ignore[arg-type]
)


# ---------------------------------------------------------------------------
# Cancel-latency overrides — replace the upstream built-in providers
# with clawcodex_ext subclasses that bound cancel latency to ~100ms
# (vs. worst-case ~60s on platforms where ``response.close()`` from
# another thread does not interrupt the blocking httpx read).
#
# The hook added to ``src.providers.get_provider_class`` checks
# ``_EXTRA_PROVIDER_CLASSES`` first, so these registrations win over
# the hardcoded if-branches in the upstream resolver.
# ---------------------------------------------------------------------------


def _ClawcodexAnthropicProvider_lazy():
    from clawcodex_ext.providers.anthropic_provider import (
        ClawcodexAnthropicProvider,
    )

    return ClawcodexAnthropicProvider


def _ClawcodexMinimaxProvider_lazy():
    from clawcodex_ext.providers.minimax_provider import (
        ClawcodexMinimaxProvider,
    )

    return ClawcodexMinimaxProvider


# Pass the existing PROVIDER_INFO entry through so the register call
# is type-correct; ``register_provider_info`` is a no-op when the name
# is already in PROVIDER_INFO, so this doesn't mutate the display dict.
register_provider(
    "anthropic",
    PROVIDER_INFO["anthropic"],  # type: ignore[arg-type]
    _ClawcodexAnthropicProvider_lazy,  # type: ignore[arg-type]
)
register_provider(
    "minimax",
    PROVIDER_INFO["minimax"],  # type: ignore[arg-type]
    _ClawcodexMinimaxProvider_lazy,  # type: ignore[arg-type]
)


# ---------------------------------------------------------------------------
# Agnes AI — media generation provider (image + video)
#
# Registered as a provider info entry (for config / UI) and in the
# **media** provider registry (separate from the chat-provider
# hierarchy).  Image and video are registered independently so they
# can be looked up by category.
#
# Config file convention (same as all providers):
#   ~/.clawcodex/config.json -> providers.agnes = {
#       "api_key": "...",
#       "base_url": "https://apihub.agnes-ai.com/v1",
#       "default_model": "agnes-image-2.1-flash",
#       "models": ["agnes-image-2.1-flash", "agnes-image-2.0-flash",
#                  "agnes-video-v2.0", "agnes-2.0-flash"]
#   }
# Env-var fallback: AGNES_API_KEY, AGNES_BASE_URL, AGNES_MODEL
# ---------------------------------------------------------------------------

# Register provider info so the config system picks up Agnes credentials.
register_provider_info(
    "agnes",
    {
        "label": "Agnes AI (Image + Video)",
        "default_base_url": "https://apihub.agnes-ai.com/v1",
        "default_model": "agnes-image-2.1-flash",
        "available_models": [
            # Image models
            "agnes-image-2.1-flash",
            "agnes-image-2.0-flash",
            # Video models
            "agnes-video-v2.0",
            # Text model (chat-compatible, for prompt expansion)
            "agnes-2.0-flash",
        ],
    },
)


def _AgnesImageProvider_lazy():
    """Lazy accessor -- import AgnesImageProvider on first use."""
    from clawcodex_ext.providers.media.image.agnes import (  # noqa: F401
        AgnesImageProvider,
    )

    return AgnesImageProvider


def _AgnesVideoProvider_lazy():
    """Lazy accessor -- import AgnesVideoProvider on first use."""
    from clawcodex_ext.providers.media.video.agnes import (  # noqa: F401
        AgnesVideoProvider,
    )

    return AgnesVideoProvider


# Register in the media provider registry (decoupled from chat).
from clawcodex_ext.providers.media.registry import media_registry

media_registry.register_image("agnes", _AgnesImageProvider_lazy)
media_registry.register_video("agnes", _AgnesVideoProvider_lazy)
