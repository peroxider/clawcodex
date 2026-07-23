"""lkb MCP — validate_task tool."""
from __future__ import annotations

from lkb import LogicalKanbanService, get_logical_kanban


def validate_task(task_id: str, change: dict) -> dict:
    """Validate a proposed task state transition."""
    runtime = get_logical_kanban(None)
    service = LogicalKanbanService(runtime)
    result = service.validate(task_id=task_id, proposed_change=change)
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return result