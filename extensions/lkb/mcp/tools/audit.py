"""lkb MCP — audit tool."""
from __future__ import annotations

from typing import Any

from lkb import get_audit_log, get_logical_kanban


def audit_task(task_id: str, since: str | None = None) -> list[dict[str, Any]]:
    """Return the audit log for a task."""
    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)
    events = audit_log.get_events(task_id=task_id, since=since)
    return [
        {
            "eventId": getattr(e, "event_id", str(idx)),
            "timestamp": str(getattr(e, "timestamp", "")),
            "type": getattr(e, "type", None),
            "taskId": getattr(e, "task_id", task_id),
            "details": getattr(e, "details", {}),
        }
        for idx, e in enumerate(events)
    ]