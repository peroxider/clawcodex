"""F-50-C stage capability mapping."""

from .models import (
    Capability,
    CapabilityKind,
    ExecutionMode,
    StageAgentMap,
    StageCapabilityProfile,
)
from .mapper import StageCapabilityMapper, ensure_stage_skills

__all__ = [
    "Capability",
    "CapabilityKind",
    "ExecutionMode",
    "StageAgentMap",
    "StageCapabilityProfile",
    "StageCapabilityMapper",
    "ensure_stage_skills",
    "ensure_arc_stage_skills",
]


def __getattr__(name: str):
    """Preserve the old ARC export without loading ARC support eagerly."""
    if name == "ensure_arc_stage_skills":
        from .arc_mapper import ensure_arc_stage_skills

        return ensure_arc_stage_skills
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
