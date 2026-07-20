"""Multi-model scheduling extension.

The router implements the existing provider interface, so it can be injected
without changing core query-loop packages.
"""

from .aggregators import (
    MajorityVoteAggregator,
    PassThroughAggregator,
    RankAggregator,
    ScoringAggregator,
)
from .config import GroupConfig, MultiModelConfig, SlotConfig
from .display import MultiModelBridge
from .factory import build_router
from .router import MultiModelRouter, RouterConfig
from .session_bridge import SessionBridge
from .slots import ProviderSlot
from .strategies import FallbackStrategy, ParallelStrategy, RoutingRule, RoutingStrategy, VotingStrategy

__all__ = [
    "MajorityVoteAggregator",
    "PassThroughAggregator",
    "RankAggregator",
    "ScoringAggregator",
    "GroupConfig",
    "MultiModelConfig",
    "SlotConfig",
    "MultiModelBridge",
    "build_router",
    "MultiModelRouter",
    "ParallelStrategy",
    "ProviderSlot",
    "RouterConfig",
    "RoutingRule",
    "RoutingStrategy",
    "FallbackStrategy",
    "SessionBridge",
    "VotingStrategy",
]
