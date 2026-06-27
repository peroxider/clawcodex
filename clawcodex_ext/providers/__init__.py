"""Downstream provider extensions — model discovery hooks and provider overrides."""

from __future__ import annotations

# Note: ``register_provider`` and ``register_provider_info`` are safe to call
# at module level because they only touch the PROVIDER_INFO dict and the
# _EXTRA_PROVIDER_CLASSES dict — they do NOT import any provider class
# immediately (avoiding the circular-import chain:
#   src.auth.codex_oauth → clawcodex_ext → … → src.auth.codex_oauth).

from src.providers import PROVIDER_INFO

from clawcodex_ext.providers.factory import register_provider, register_provider_info


# ---------------------------------------------------------------------------
# Extend built-in provider model lists
#
# The upstream PROVIDER_INFO dict only has a subset of models. These
# extensions merge additional model variants (OpenRouter-style paths,
# newer model versions, etc.) so they show up in UI/CLI listings
# without modifying ``src/providers/__init__.py``.
#
# This code runs at import time as a side-effect of ``import clawcodex_ext``
# (see ``clawcodex_ext/__init__.py``).
# ---------------------------------------------------------------------------


def _extend_builtin_models() -> None:
    """Extend built-in provider model lists with downstream additions.

    Idempotent: on second call the ``extend`` would be a no-op because
    the upstream models are already present (the extended lists are
    supersets of the upstream baseline).
    """
    # Anthropic — add OpenRouter-style paths + newer variants
    anthropic_models = PROVIDER_INFO.setdefault("anthropic", {}).setdefault(
        "available_models", []
    )
    _anthropic_extras = [
        "anthropic/claude-3.5-haiku",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-opus-4.1",
        "anthropic/claude-sonnet-4.5",
    ]
    for m in _anthropic_extras:
        if m not in anthropic_models:
            anthropic_models.append(m)

    # OpenAI — add OpenRouter-style paths + newer variants
    openai_models = PROVIDER_INFO.setdefault("openai", {}).setdefault(
        "available_models", []
    )
    _openai_extras = [
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-5",
        "openai/gpt-5-mini",
    ]
    for m in _openai_extras:
        if m not in openai_models:
            openai_models.append(m)

    # Z.ai / GLM — add OpenRouter-style paths. Upstream renamed the ``glm``
    # provider to ``zai`` (``glm`` is now only a ``PROVIDER_ALIASES`` spelling),
    # so extend the canonical ``zai`` entry. Guard on existence so we never
    # fabricate a label-less stub entry that would break ``AVAILABLE_PROVIDERS``.
    glm_models = PROVIDER_INFO.get("zai", PROVIDER_INFO.get("glm", {})).setdefault(
        "available_models", []
    )
    _glm_extras = [
        "zai/glm-3-turbo",
        "zai/glm-4",
        "zai/glm-4-air",
        "zai/glm-4-flash",
        "zai/glm-4-plus",
        "zai/glm-4.5",
        "zai/glm-4.6",
        "zai/glm-4.7",
        "zai/glm-5",
        "zai/glm-5-turbo",
    ]
    for m in _glm_extras:
        if m not in glm_models:
            glm_models.append(m)

    # DeepSeek — add OpenRouter-style paths + downstream variants
    deepseek_models = PROVIDER_INFO.setdefault("deepseek", {}).setdefault(
        "available_models", []
    )
    _deepseek_extras = [
        "deepseek/deepseek-chat-v3.1",
        "deepseek/deepseek-r1-0528",
        "deepseek/deepseek-v3.1-terminus",
        "deepseek/deepseek-v3.2",
        "deepseek/deepseek-v3.2-speciale",
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
    ]
    for m in _deepseek_extras:
        if m not in deepseek_models:
            deepseek_models.append(m)

    # Gemini — add OpenRouter-style paths
    gemini_models = PROVIDER_INFO.setdefault("gemini", {}).setdefault(
        "available_models", []
    )
    _gemini_extras = [
        "google/gemini-2.0-flash",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
    ]
    for m in _gemini_extras:
        if m not in gemini_models:
            gemini_models.append(m)

    # Minimax — add M3 series (current default in ~/.clawcodex/config.json).
    # The upstream PROVIDER_INFO entry only lists the M2.x line; M3 ships as a
    # downstream-only variant served by the same Anthropic-compatible endpoint.
    minimax_models = PROVIDER_INFO.setdefault("minimax", {}).setdefault(
        "available_models", []
    )
    _minimax_extras = [
        "MiniMax-M3",
        "MiniMax-M3-highspeed",
    ]
    for m in _minimax_extras:
        if m not in minimax_models:
            minimax_models.append(m)


_extend_builtin_models()

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


def _KimiProvider_lazy():
    """Lazy accessor that defers the import until first use."""
    from clawcodex_ext.providers.kimi_provider import KimiProvider

    return KimiProvider


register_provider(
    "kimi",
    {
        "label": "Kimi (Moonshot AI)",
        "default_base_url": "https://api.moonshot.ai/v1",
        "default_model": "kimi-k2.6",
        "available_models": [
            # K2.x flagship / multi-modal models
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2.7-code",
            "kimi-k2.7-code-highspeed",
            # Moonshot V1 generation models
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            # Vision-capable V1 previews
            "moonshot-v1-8k-vision-preview",
            "moonshot-v1-32k-vision-preview",
            "moonshot-v1-128k-vision-preview",
        ],
    },
    _KimiProvider_lazy,  # type: ignore[arg-type]
)


def _KimiCodingProvider_lazy():
    """Lazy accessor that defers the import until first use."""
    from clawcodex_ext.providers.kimi_coding_provider import KimiCodingProvider

    return KimiCodingProvider


register_provider(
    "kimi-coding",
    {
        "label": "Kimi Coding (Moonshot AI)",
        "default_base_url": "https://api.kimi.com/coding",
        "default_model": "kimi-code",
        "available_models": [
            "kimi-code",
        ],
    },
    _KimiCodingProvider_lazy,  # type: ignore[arg-type]
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
