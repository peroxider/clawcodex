"""SOPAssistantProvider Protocol — lightweight chat boundary for SOP grouping.

Trims the full ``clawcodex_ext.providers.base.BaseProvider`` interface
down to the single capability the ``skill_grouper`` LLM_SEMANTIC path
actually uses::

    response = provider.chat(messages)
    raw = response.content  # str

The lighter surface keeps the SOP converter core independent of the
provider abstraction (so the ``sop_converter/core/`` re-packaging
target in Phase 4 doesn't need to drag in model wiring), while still
admitting a thin adapter over ``BaseProvider`` via the
``SOPAssistantProviderAdapter`` (Phase 3+).

Messages accept anything that BaseProvider accepts — either
``dict[str, Any]`` or the upstream ``ChatMessage`` dataclass — so
callers in either shape keep working.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["SOPAssistantProviderProtocol"]


# Accepted shapes mirror ``clawcodex_ext.providers.base.MessageInput``
# (``ChatMessage | dict[str, Any]``); typed loosely here so the Protocol
# stays duck-typed and avoids dragging the provider package into the
# Layer-2 import surface.
SOPProviderMessage = Any


@runtime_checkable
class SOPAssistantProviderProtocol(Protocol):
    """Single-shot chat boundary used by ``skill_grouper``.

    Implementations MUST return a ``str`` (the model's full assistant
    message content). Streaming, tool-use, and structured-output knobs
    are intentionally out of scope — those belong in
    :class:`extensions.capabilities.provider_protocol.LLMProviderProtocol`
    (already present in the capabilities package).
    """

    def chat(self, messages: list[SOPProviderMessage]) -> str: ...
