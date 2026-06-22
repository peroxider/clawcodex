"""Compatibility shim for the LiteLLM provider extension."""

from __future__ import annotations

from extensions.providers_ext import (
    LiteLLMProvider,
    create_litellm_provider,
    is_litellm_available,
)

__all__ = [
    "LiteLLMProvider",
    "create_litellm_provider",
    "is_litellm_available",
]
