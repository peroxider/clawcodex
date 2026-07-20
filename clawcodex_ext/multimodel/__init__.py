"""Multi-model scheduling extension.

This package currently exposes the response aggregators.  Routers and
strategies can depend on these classes without modifying the core provider
or query-loop packages.
"""

from .aggregators import (
    MajorityVoteAggregator,
    PassThroughAggregator,
    RankAggregator,
    ScoringAggregator,
)
from .config import GroupConfig, MultiModelConfig, SlotConfig

__all__ = [
    "MajorityVoteAggregator",
    "PassThroughAggregator",
    "RankAggregator",
    "ScoringAggregator",
    "GroupConfig",
    "MultiModelConfig",
    "SlotConfig",
]
