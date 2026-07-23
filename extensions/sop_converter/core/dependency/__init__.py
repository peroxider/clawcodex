"""Tool Dependency Graph — F-55 L2.

Builds a directed graph of tool lifecycle dependencies from a parsed
``list[SourceComponent]`` and persists it to a bundle-local
``tool-dependencies.yaml`` so downstream consumers (task guide, system
prompts, ToolSearch ranker) can reason about create→invoke chains
without re-deriving the heuristics at runtime.

Layering
--------
* ``models``        — pure data classes
* ``heuristics``    — pair / shared-param rules
* ``detector``      — ``detect_lifecycle_patterns()`` entry point
* ``writer``        — YAML writer (with JSON fallback when PyYAML missing)
* ``reader``        — load + tolerant corruption handling
"""

from __future__ import annotations

from .detector import detect_lifecycle_patterns
from .models import (
    HiddenStep,
    IntentGroup,
    PriorityRoute,
    ToolDependency,
    ToolDependencyGraph,
)
from .reader import load_tool_dependencies, merge_overrides
from .writer import write_tool_dependencies

__all__ = [
    "HiddenStep",
    "IntentGroup",
    "PriorityRoute",
    "ToolDependency",
    "ToolDependencyGraph",
    "detect_lifecycle_patterns",
    "load_tool_dependencies",
    "merge_overrides",
    "write_tool_dependencies",
]
