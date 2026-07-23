"""Orchestrator-facing facade for Logical Kanban (F-140).

This module exposes a small, stable API that orchestrators and dashboards can
use to benefit from LKB without importing solver internals such as
``SolverAdapter``, ``SolverPipeline`` or ``Layer1RuleEngine``.

All functions are thin wrappers over the existing Task V2 tool adapters and
context readers.  They return plain JSON-serializable dictionaries so that
callers running in a different process or thread can consume the results easily.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .adapters import prepare_task_change
from .audit import get_audit_log
from .context_adapter import task_lkb_view, task_list_view
from .flags import is_logical_kanban_enabled
from .runtime import get_logical_kanban


def validate_task_transition(
    context: Any,
    task_id: str,
    status: str,
    *,
    actor: str = "orchestrator",
) -> dict[str, Any]:
    """Validate a status transition without mutating ``context.tasks``.

    The function follows the same propose/validate/commit contract used by
    ``TaskUpdate``.  If the transition is allowed it returns a committed
    payload; otherwise it returns a denial with a human-readable reason and
    repair suggestions.

    Args:
        context: Current tool context.
        task_id: Task identifier.
        status: Target status (``pending``, ``in_progress``, ``completed``,
            or ``deleted``).
        actor: Actor label recorded on the proposal.

    Returns:
        A dictionary with ``allowed`` (bool), ``validationRunId``,
        ``decision`` (``committed``/``denied``), ``result``, ``message``,
        ``repairSuggestions`` and the full LKB detail under ``lkb``.
    """
    if not is_logical_kanban_enabled():
        return {
            "allowed": True,
            "validationRunId": None,
            "decision": "committed",
            "result": "pass",
            "message": "Logical Kanban is disabled; transition allowed by default.",
            "repairSuggestions": [],
            "lkb": None,
        }

    denied, lkb = prepare_task_change(
        change_kind="transition_status",
        tool_input={
            "taskId": task_id,
            "status": status,
            "_actor": actor,
        },
        context=context,
    )

    if denied is not None:
        lkb_payload = denied.output.get("lkb") or {}
        return {
            "allowed": False,
            "validationRunId": lkb_payload.get("validationRunId"),
            "decision": "denied",
            "result": lkb_payload.get("result", "fail"),
            "message": lkb_payload.get("humanMessage", "Validation denied."),
            "repairSuggestions": lkb_payload.get("repairSuggestions", []),
            "lkb": lkb_payload,
        }

    return {
        "allowed": True,
        "validationRunId": lkb.get("validationRunId") if lkb else None,
        "decision": "committed",
        "result": lkb.get("result", "pass") if lkb else "pass",
        "message": "Transition is valid.",
        "repairSuggestions": lkb.get("nextActions", []) if lkb else [],
        "lkb": lkb,
    }

def task_ready_state(context: Any, task_id: str) -> dict[str, Any]:
    """Return the derived LKB readiness state for a task.

    The result includes the task's own ``status`` plus derived fields such as
    ``derivedStatus``, ``blockedBy``, ``blockedReason``, ``nextActions``,
    ``last_validation_run_id`` and any stale assumptions.
    """
    if not is_logical_kanban_enabled():
        task = context.tasks.get(task_id)
        return {
            "taskId": task_id,
            "status": task.get("status") if isinstance(task, dict) else None,
            "derivedStatus": "unknown",
            "blockedBy": [],
            "blockedReason": None,
            "nextActions": [],
            "last_validation_run_id": None,
        }

    view = task_lkb_view(context, task_id, include_proof_trace=False)
    task = context.tasks.get(task_id)
    return {
        "taskId": task_id,
        "status": task.get("status") if isinstance(task, dict) else None,
        "derivedStatus": view.get("derivedStatus"),
        "blockedBy": view.get("blockedBy", []),
        "blockedReason": view.get("blockedReason"),
        "nextActions": view.get("nextActions", []),
        "last_validation_run_id": view.get("last_validation_run_id"),
        "latestValidationResult": view.get("latestValidationResult"),
        "staleAssumptions": view.get("staleAssumptions"),
    }

def task_list_summary(context: Any) -> list[dict[str, Any]]:
    """Return a deterministic summary of all tasks, including LKB metadata."""
    return task_list_view(context, include_lkb=is_logical_kanban_enabled())

def latest_denial_for_task(context: Any, task_id: str) -> dict[str, Any] | None:
    """Return the most recent LKB denial for ``task_id``, if any."""
    runtime = get_logical_kanban(context)
    denials = getattr(runtime, "latest_denials", None)
    if not isinstance(denials, dict):
        return None
    denial = denials.get(task_id)
    return dict(denial) if isinstance(denial, dict) else None

def acceptance_proof_required(context: Any, task_id: str) -> bool:
    """Return whether a completed status transition requires acceptance proof."""
    if not is_logical_kanban_enabled():
        return False
    runtime = get_logical_kanban(context)
    if runtime.strict_acceptance_enabled:
        return True
    task = context.tasks.get(task_id)
    if not isinstance(task, dict):
        return False
    metadata = task.get("metadata") or {}
    lkb_metadata = metadata.get("lkb") or {} if isinstance(metadata, dict) else {}
    return bool(lkb_metadata.get("strict_acceptance", runtime.strict_acceptance_enabled))

def read_audit_events_for_run(
    context: Any,
    *,
    run_id: str | None = None,
    task_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read LKB audit events for a validation run or task.

    This is the dashboard/event-contract consumer from F-137.  It returns the
    most recent matching events first as plain dictionaries.

    When ``run_id`` is provided it is matched against the canonical
    ``validationRunId`` field (``V-*``) rather than session id or payload
    substrings.
    """
    log = get_audit_log(context)
    events = log.query(
        validation_run_id=run_id,
        task_id=task_id,
        limit=limit,
    )
    return [event.to_dict() for event in events]

__all__ = [
    "acceptance_proof_required",
    "latest_denial_for_task",
    "read_audit_events_for_run",
    "task_list_summary",
    "task_ready_state",
    "validate_task_transition",
]
