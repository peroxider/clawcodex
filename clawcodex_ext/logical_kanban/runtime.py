"""Runtime holder for Logical Kanban services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .service import LogicalKanbanService


@dataclass(slots=True)
class LogicalKanbanRuntime:
    service: LogicalKanbanService = field(default_factory=LogicalKanbanService)
    strict_acceptance_enabled: bool = False
    strict_logical_todo_enabled: bool = False
    latest_denials: dict[str, dict[str, Any]] = field(default_factory=dict)


def get_logical_kanban(context: Any) -> LogicalKanbanRuntime:
    runtime = getattr(context, "logical_kanban", None)
    if runtime is None:
        runtime = LogicalKanbanRuntime()
        try:
            context.logical_kanban = runtime
        except AttributeError:
            pass
    return runtime
