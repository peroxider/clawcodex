"""F-120 Agent Dashboard — built-in data sources.

This package ships the two data sources the F-120 plan §3 commits
to in Phase 2: :class:`GoalDashboardSource` (reads from
``GoalService``) and :class:`TasksDashboardSource` (reads from
``ToolContext.tasks``). Optional Orchestrator / SOP sources live in
``extensions/orchestrator`` and ``extensions/sop_converter`` and
register themselves against the default registry on import.
"""

from __future__ import annotations

from .goal_source import GoalDashboardSource
from .tasks_source import TasksDashboardSource

__all__ = [
    "GoalDashboardSource",
    "TasksDashboardSource",
]
