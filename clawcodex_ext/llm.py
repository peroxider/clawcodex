"""Lightweight LLM access — one-shot text completion without agent infrastructure.

Usage:

    from clawcodex_ext.llm import llm_complete

    answer = await llm_complete("What is 2+2?")
    answer = await llm_complete(
        "Explain in one sentence.",
        system_prompt="You are a terse assistant.",
        model="deepseek-v4-flash",
    )

Raises ``RuntimeError`` when the provider is not configured
(no API key, not logged in, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from clawcodex_ext.providers.base import BaseProvider, ChatMessage
from clawcodex_ext.providers.runtime import build_provider_from_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache: provider/fallback_model are resolved once per process,
# but the provider instance itself is **not** cached — each call creates a
# fresh ``BaseProvider`` so config changes (e.g. runtime model switch) take
# effect without a restart.  This is negligible overhead (∼1 ms per call).
# ---------------------------------------------------------------------------

_DEFAULT_PROVIDER: str | None = None
_DEFAULT_MODEL: str | None = None


def _get_default_provider() -> str:
    """Resolve the default provider name (cached after first call)."""
    global _DEFAULT_PROVIDER
    if _DEFAULT_PROVIDER is None:
        from src.config import get_default_provider as _resolve

        _DEFAULT_PROVIDER = _resolve()
    return _DEFAULT_PROVIDER


def _get_default_model(provider_name: str) -> str | None:
    """Resolve the default model for *provider_name* (cached)."""
    global _DEFAULT_MODEL
    if _DEFAULT_MODEL is None:
        from src.config import get_provider_config

        cfg = get_provider_config(provider_name)
        _DEFAULT_MODEL = cfg.get("default_model")
    return _DEFAULT_MODEL


async def llm_complete(
    prompt: str,
    *,
    system_prompt: str = "",
    provider_name: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send a single prompt to the configured LLM and return the text reply.

    Parameters
    ----------
    prompt:
        The user message to send.
    system_prompt:
        Optional system-level instruction.
    provider_name:
        Provider to use (default: the user's configured default provider).
    model:
        Model to use (default: the provider's default model).
    temperature:
        Optional sampling temperature override.
    max_tokens:
        Optional max output tokens override.

    Returns
    -------
    The model's text response, stripped of leading/trailing whitespace.

    Raises
    ------
    RuntimeError
        If the provider is not configured / not logged in.
    """
    provider_name = provider_name or _get_default_provider()
    model = model or _get_default_model(provider_name)

    provider: BaseProvider = build_provider_from_config(provider_name, model)

    messages: list[ChatMessage] = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    messages.append(ChatMessage(role="user", content=prompt))

    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    logger.debug(
        "llm_complete: provider=%s model=%s system=%d chars prompt=%d chars",
        provider_name,
        model,
        len(system_prompt),
        len(prompt),
    )

    resp = await provider.chat_async(messages, tools=None, **kwargs)

    result = (resp.content or "").strip()
    logger.debug("llm_complete: response=%d chars finish=%s", len(result), resp.finish_reason)
    return result
