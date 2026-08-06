"""Parallel scheduling for aggregator-backed voting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawcodex_ext.capabilities.multimodel_protocol import AggregatorProtocol, MultiModelResult
from clawcodex_ext.providers.base import MessageInput

from .parallel import ParallelStrategy


@dataclass
class VotingStrategy(ParallelStrategy):
    """Run candidates in parallel; the router's aggregator picks a response.

    ``aggregator`` is optional to support a self-contained strategy while
    retaining the router-level aggregator injection documented for multi-model dispatch.
    """

    aggregator: AggregatorProtocol | None = None
    min_votes: int = 2
    name = "voting"

    async def execute(
        self, router: Any, messages: list[MessageInput], **kwargs: Any
    ) -> list[MultiModelResult]:
        return await super().execute(router, messages, **kwargs)
