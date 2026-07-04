"""Deprecated forwarding shim for ``extensions.providers_ext.litellm_provider``.

The canonical implementation has moved to
:mod:`clawcodex_ext.providers._litellm_adapter` (Phase K migration).
This module re-exports the module-level helpers so legacy
``extensions.providers_ext.litellm_provider._load_litellm`` /
``is_litellm_available`` references (used by test mocks) continue to
work.

New code should import from
``clawcodex_ext.providers._litellm_adapter`` directly.
"""

from clawcodex_ext.providers._litellm_adapter import (  # noqa: F401
    LiteLLMProvider,
    _load_litellm,
    create_litellm_provider,
    is_litellm_available,
)

__all__ = [
    "LiteLLMProvider",
    "_load_litellm",
    "create_litellm_provider",
    "is_litellm_available",
]
