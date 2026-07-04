"""Deprecated forwarding shim for the LiteLLM provider.

The canonical implementation has moved to
:mod:`clawcodex_ext.providers._litellm_adapter` (Phase K migration).
This module re-exports the public surface so legacy
``from extensions.providers_ext import …`` call sites continue to work.

New code should import from
``clawcodex_ext.providers._litellm_adapter`` directly.  The
``extensions/providers_ext/`` namespace is preserved only for backward
compatibility with existing test mocks and downstream forks that
target the old path.
"""

from clawcodex_ext.providers._litellm_adapter import (  # noqa: F401
    LiteLLMProvider,
    create_litellm_provider,
    is_litellm_available,
)

__all__ = [
    "LiteLLMProvider",
    "create_litellm_provider",
    "is_litellm_available",
]
