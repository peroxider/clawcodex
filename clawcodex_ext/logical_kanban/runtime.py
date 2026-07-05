"""Runtime holder for Logical Kanban services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .service import LogicalKanbanService
    from .truth_maintenance import TruthMaintenanceSystem


@dataclass(slots=True)
class LogicalKanbanRuntime:
    service: "LogicalKanbanService" = field(default_factory=lambda: _make_service())
    tms: "TruthMaintenanceSystem" = field(default_factory=lambda: _make_tms())
    strict_mode_enabled: bool = False
    strict_acceptance_enabled: bool = False
    strict_logical_todo_enabled: bool = False
    latest_denials: dict[str, dict[str, Any]] = field(default_factory=dict)


def _make_service() -> "LogicalKanbanService":
    from .service import LogicalKanbanService
    return LogicalKanbanService()


def _make_tms() -> "TruthMaintenanceSystem":
    from .truth_maintenance import TruthMaintenanceSystem
    return TruthMaintenanceSystem()


def get_logical_kanban(context: Any) -> "LogicalKanbanRuntime":
    runtime = getattr(context, "logical_kanban", None)
    if runtime is None:
        runtime = LogicalKanbanRuntime()
        try:
            context.logical_kanban = runtime
        except AttributeError:
            pass
    return runtime
