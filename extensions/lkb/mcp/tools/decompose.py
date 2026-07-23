"""lkb MCP — decompose_task tool."""
from __future__ import annotations

from lkb import TaskDecomposer


def decompose_task(goal: str, context: dict | None = None, use_methods: list[str] | None = None) -> str:
    """Decompose a goal into a validated task plan and return JSON."""
    decomposer = TaskDecomposer()
    plan = decomposer.decompose(
        goal=goal,
        context=context or {},
        method_refs=tuple(use_methods or []),
    )
    return plan.to_json()