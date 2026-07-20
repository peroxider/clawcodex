"""The no-selection multi-model aggregator."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.capabilities.multimodel_protocol import AggregatedOutput, MultiModelResult

from .base import fallback_output


class PassThroughAggregator:
    """Keep every result and select the first successful one for compatibility."""

    async def aggregate(
        self, results: list[MultiModelResult], context: dict[str, Any]
    ) -> AggregatedOutput:
        del context
        return fallback_output(results)
