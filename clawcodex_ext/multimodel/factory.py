"""Turn persistent model-group settings into a runtime provider."""

from __future__ import annotations

from typing import Callable

from .aggregators import MajorityVoteAggregator, PassThroughAggregator, RankAggregator, ScoringAggregator
from .config import GroupConfig
from .router import MultiModelRouter, RouterConfig
from .slots import ProviderSlot
from .strategies import FallbackStrategy, ParallelStrategy, RoutingStrategy, VotingStrategy


def build_router(group: GroupConfig, provider_builder: Callable[[str, str], object]) -> MultiModelRouter:
    """Build a router from a validated group without importing runtime modules.

    ``provider_builder`` is injected to keep configuration portable and make
    this construction path straightforward to test without credentials.
    """
    slots = [
        ProviderSlot(
            name=item.name,
            provider=provider_builder(item.provider, item.model),  # type: ignore[arg-type]
            model=item.model,
            weight=item.weight,
            timeout_ms=item.timeout_ms,
            enabled=item.enabled,
        )
        for item in group.slots
    ]
    aggregator = _aggregator(group)
    if group.strategy == "parallel":
        strategy = ParallelStrategy()
    elif group.strategy == "voting":
        strategy = VotingStrategy(aggregator=aggregator or MajorityVoteAggregator(group.min_votes or 2))
        aggregator = None
    elif group.strategy == "fallback":
        strategy = FallbackStrategy()
    elif group.strategy == "routing":
        strategy = RoutingStrategy(fallback_slot=slots[0].name)
    else:  # validate_group keeps this defensive branch unreachable
        raise ValueError(f"unknown multi-model strategy: {group.strategy}")
    return MultiModelRouter(slots, strategy, aggregator, config=RouterConfig(group.max_concurrent))


def _aggregator(group: GroupConfig):
    if group.aggregator is None:
        return None
    if group.aggregator == "passthrough":
        return PassThroughAggregator()
    if group.aggregator == "majority":
        return MajorityVoteAggregator(group.min_votes or 2)
    if group.aggregator == "rank":
        return RankAggregator()
    if group.aggregator == "scoring":
        return ScoringAggregator()
    raise ValueError(f"unknown multi-model aggregator: {group.aggregator}")
