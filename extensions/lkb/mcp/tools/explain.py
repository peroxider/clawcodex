"""lkb MCP — explain tool."""
from __future__ import annotations

from lkb import get_audit_log, get_logical_kanban


def explain_task(task_id: str) -> dict:
    """Explain the reasoning chain for a task."""
    runtime = get_logical_kanban(None)
    audit_log = get_audit_log(runtime)
    return runtime.explain_task(task_id, audit_log)