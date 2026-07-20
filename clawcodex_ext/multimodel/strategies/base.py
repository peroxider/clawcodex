"""Common strategy base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from clawcodex_ext.capabilities.multimodel_protocol import MultiModelResult
from clawcodex_ext.providers.base import MessageInput


class MultiModelStrategyBase(ABC):
    """Small concrete-friendly base for the scheduling protocol."""

    name: str

    @abstractmethod
    async def execute(
        self, router: Any, messages: list[MessageInput], **kwargs: Any
    ) -> list[MultiModelResult]:
        """Execute one router turn and retain every attempted result."""
