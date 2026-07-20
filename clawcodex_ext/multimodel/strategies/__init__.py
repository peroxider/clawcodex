"""Scheduling strategies used by :class:`MultiModelRouter`."""

from .base import MultiModelStrategyBase
from .fallback import FallbackStrategy
from .parallel import ParallelStrategy
from .routing import RoutingRule, RoutingStrategy
from .voting import VotingStrategy

__all__ = [
    "FallbackStrategy", "MultiModelStrategyBase", "ParallelStrategy", "RoutingRule",
    "RoutingStrategy", "VotingStrategy",
]
