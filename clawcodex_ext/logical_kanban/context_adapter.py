"""Build Logical Kanban facts from the current tool context.

The adapter is intentionally read-only. It normalizes the legacy TodoWrite
surface and the structured Task V2 surface into one dependency graph, then
derives the light-weight facts that the foundation service needs today.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from .types import FactsSnapshot, ValidationIssue

if TYPE_CHECKING:
    from clawcodex_ext.tool_system.context import ToolContext


def build_facts_snapshot(context: "ToolContext") -> FactsSnapshot:
    todos = tuple(dict(t) for t in getattr(context, "todos", []) or [])
    raw_tasks = {
        task_id: dict(task)
        for task_id, task in (getattr(context, "tasks", {}) or {}).items()
        if not (task.get("metadata") or {}).get("_internal")
    }

    completed_ids = frozenset(
        task_id for task_id, task in raw_tasks.items() if task.get("status") == "completed"
    )
    normalized_tasks = {
        task_id: _normalize_task(task_id, task) for task_id, task in raw_tasks.items()
    }

    outgoing: dict[str, set[str]] = {task_id: set() for task_id in normalized_tasks}
    incoming: dict[str, set[str]] = {task_id: set() for task_id in normalized_tasks}
    warnings: list[ValidationIssue] = []

    for task_id, task in normalized_tasks.items():
        for blocker_id in task["blocked_by"]:
            _add_edge(
                prerequisite=blocker_id,
                dependent=task_id,
                raw_tasks=raw_tasks,
                outgoing=outgoing,
                incoming=incoming,
                warnings=warnings,
            )
            blocker = normalized_tasks.get(blocker_id)
            if blocker is not None and task_id not in blocker["blocks"]:
                warnings.append(
                    _warning(
                        "dependency_direction_mismatch",
                        f"Task {task_id} lists {blocker_id} in blockedBy, but {blocker_id} does not list {task_id} in blocks.",
                        "LKB-CONSISTENCY-001",
                        task_id=task_id,
                        blockers=(blocker_id,),
                    )
                )

        for dependent_id in task["blocks"]:
            _add_edge(
                prerequisite=task_id,
                dependent=dependent_id,
                raw_tasks=raw_tasks,
                outgoing=outgoing,
                incoming=incoming,
                warnings=warnings,
            )
            dependent = normalized_tasks.get(dependent_id)
            if dependent is not None and task_id not in dependent["blocked_by"]:
                warnings.append(
                    _warning(
                        "dependency_direction_mismatch",
                        f"Task {task_id} lists {dependent_id} in blocks, but {dependent_id} does not list {task_id} in blockedBy.",
                        "LKB-CONSISTENCY-001",
                        task_id=dependent_id,
                        blockers=(task_id,),
                    )
                )

    cycle_task_ids = frozenset(_cycle_nodes(outgoing))
    blocked_ids: set[str] = set()
    ready_ids: set[str] = set()
    for task_id, blockers in incoming.items():
        task = normalized_tasks[task_id]
        active_blockers = [bid for bid in sorted(blockers) if bid not in completed_ids]
        if task["status"] != "completed" and active_blockers:
            blocked_ids.add(task_id)
        elif task["status"] != "completed" and task_id not in cycle_task_ids:
            ready_ids.add(task_id)

    facts = _build_facts(
        todos=todos,
        tasks=normalized_tasks,
        outgoing=outgoing,
        incoming=incoming,
    )
    payload = {
        "todos": todos,
        "tasks": raw_tasks,
        "normalizedTasks": normalized_tasks,
        "facts": facts,
        "completedIds": sorted(completed_ids),
        "dependencyGraph": _freeze_graph(outgoing),
        "blockedBy": _freeze_graph(incoming),
        "readyIds": sorted(ready_ids),
        "blockedIds": sorted(blocked_ids),
        "cycleTaskIds": sorted(cycle_task_ids),
        "warnings": [w.to_dict() for w in warnings],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    return FactsSnapshot(
        todos=todos,
        tasks=raw_tasks,
        normalized_tasks=normalized_tasks,
        facts=facts,
        completed_ids=completed_ids,
        dependency_graph=_freeze_graph(outgoing),
        blocked_by=_freeze_graph(incoming),
        ready_ids=frozenset(ready_ids),
        blocked_ids=frozenset(blocked_ids),
        cycle_task_ids=cycle_task_ids,
        warnings=tuple(warnings),
        hash=f"sha256:{digest}",
    )


def active_blockers(snapshot: FactsSnapshot, task_id: str) -> tuple[str, ...]:
    blockers = snapshot.blocked_by.get(task_id, ())
    return tuple(bid for bid in blockers if bid not in snapshot.completed_ids)


def dependency_closure(snapshot: FactsSnapshot, task_id: str) -> frozenset[str]:
    seen: set[str] = set()
    stack = list(snapshot.blocked_by.get(task_id, ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(snapshot.blocked_by.get(current, ()))
    return frozenset(seen)


def task_list_view(context: "ToolContext", *, include_lkb: bool = False) -> list[dict[str, Any]]:
    snapshot = build_facts_snapshot(context)
    rows: list[dict[str, Any]] = []
    for task_id, task in snapshot.normalized_tasks.items():
        active = active_blockers(snapshot, task_id)
        row = {
            "id": task_id,
            "subject": task["subject"],
            "status": task["status"],
            **({"owner": task["owner"]} if task.get("owner") else {}),
            "blockedBy": list(active),
        }
        if include_lkb:
            row["lkb"] = task_lkb_view(context, task_id, snapshot=snapshot)
        rows.append(row)
    rows.sort(key=lambda x: x["id"])
    return rows


def task_lkb_view(
    context: "ToolContext",
    task_id: str,
    *,
    snapshot: FactsSnapshot | None = None,
    include_proof_trace: bool = False,
) -> dict[str, Any]:
    snapshot = snapshot or build_facts_snapshot(context)
    task = snapshot.normalized_tasks.get(task_id)
    if task is None:
        return {
            "derivedStatus": "needs_recheck",
            "blockedBy": [],
            "blockedReason": "Task is missing from the current LKB snapshot.",
            "nextActions": ["refresh_task"],
            "validation_status": "missing",
            "last_validation_run_id": None,
        }

    blockers = active_blockers(snapshot, task_id)
    warnings = [
        w
        for w in snapshot.warnings
        if w.task_id == task_id and w.code != "dependency_direction_mismatch"
    ]
    lkb_metadata = ((task.get("metadata") or {}).get("lkb") or {})
    validation_run_id = lkb_metadata.get("validation_run_id")
    latest_denial = _latest_denial(context, task_id)

    if blockers:
        derived_status = "blocked"
    elif task_id in snapshot.cycle_task_ids or warnings:
        derived_status = "needs_recheck"
    else:
        derived_status = "ready"

    blocked_reason = None
    next_actions: list[str] = []
    if blockers:
        blocked_reason = f"Blocked by incomplete task(s): {', '.join(blockers)}."
        next_actions = [f"complete:{blocker}" for blocker in blockers]
    elif task_id in snapshot.cycle_task_ids:
        blocked_reason = "Dependency graph contains a cycle involving this task."
        next_actions = ["remove_dependency_cycle"]
    elif warnings:
        blocked_reason = warnings[0].message
        next_actions = ["repair_dependency_metadata"]
    else:
        next_actions = ["start_task"] if task["status"] == "pending" else []

    out: dict[str, Any] = {
        "derivedStatus": derived_status,
        "blockedBy": list(blockers),
        "blockedReason": blocked_reason,
        "nextActions": next_actions,
        "validation_status": (
            "denied" if latest_denial else ("validated" if validation_run_id else "unknown")
        ),
        "last_validation_run_id": validation_run_id,
        "latestDenialReason": latest_denial,
    }
    if include_proof_trace:
        out["proof_trace"] = []
    return out


def _latest_denial(context: "ToolContext", task_id: str) -> dict[str, Any] | None:
    runtime = getattr(context, "logical_kanban", None)
    denials = getattr(runtime, "latest_denials", None)
    if not isinstance(denials, dict):
        return None
    denial = denials.get(task_id)
    return dict(denial) if isinstance(denial, dict) else None


def _normalize_task(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(task.get("metadata") or {})
    lkb_metadata = dict((metadata.get("lkb") or {}) if isinstance(metadata, dict) else {})
    return {
        "id": task_id,
        "subject": str(task.get("subject") or task.get("content") or ""),
        "description": str(task.get("description") or ""),
        "status": _normalize_status(task.get("status")),
        "owner": task.get("owner") if isinstance(task.get("owner"), str) else None,
        "blocks": _string_list(task.get("blocks")),
        "blocked_by": _string_list(task.get("blockedBy")),
        "metadata": {
            **metadata,
            "lkb": {
                "acceptance_proof": lkb_metadata.get("acceptance_proof"),
                "assertions": _string_list(lkb_metadata.get("assertions")),
                "assumptions": _string_list(lkb_metadata.get("assumptions")),
                "validation_run_id": lkb_metadata.get("validation_run_id"),
            },
        },
    }


def _normalize_status(value: Any) -> str:
    if value in {"pending", "in_progress", "completed"}:
        return str(value)
    return "pending"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item not in out:
            out.append(item)
    return out


def _add_edge(
    *,
    prerequisite: str,
    dependent: str,
    raw_tasks: dict[str, dict[str, Any]],
    outgoing: dict[str, set[str]],
    incoming: dict[str, set[str]],
    warnings: list[ValidationIssue],
) -> None:
    if prerequisite not in raw_tasks or dependent not in raw_tasks:
        missing = prerequisite if prerequisite not in raw_tasks else dependent
        warnings.append(
            _warning(
                "dangling_blocker",
                f"Dependency from {prerequisite} to {dependent} references missing task {missing}.",
                "LKB-CONSISTENCY-002",
                task_id=dependent,
                blockers=(prerequisite,),
            )
        )
        return
    outgoing.setdefault(prerequisite, set()).add(dependent)
    incoming.setdefault(dependent, set()).add(prerequisite)


def _build_facts(
    *,
    todos: tuple[dict[str, Any], ...],
    tasks: dict[str, dict[str, Any]],
    outgoing: dict[str, set[str]],
    incoming: dict[str, set[str]],
) -> tuple[str, ...]:
    facts: list[str] = []
    for task_id, task in tasks.items():
        status = task["status"]
        facts.extend((f"Task({task_id})", f"Status({task_id}, {status})"))
        if status == "pending":
            facts.append(f"Pending({task_id})")
        elif status == "in_progress":
            facts.append(f"Doing({task_id})")
        elif status == "completed":
            facts.append(f"Done({task_id})")
        if task.get("owner"):
            facts.append(f"Owner({task_id}, {task['owner']})")
        if ((task.get("metadata") or {}).get("lkb") or {}).get("acceptance_proof"):
            facts.append(f"HasAcceptanceProof({task_id})")

    for prerequisite, dependents in outgoing.items():
        for dependent in sorted(dependents):
            facts.append(f"Blocks({prerequisite}, {dependent})")
    for dependent, prerequisites in incoming.items():
        for prerequisite in sorted(prerequisites):
            facts.append(f"Requires({prerequisite}, {dependent})")

    for index, todo in enumerate(todos):
        todo_id = f"todo:{index}"
        status = _normalize_status(todo.get("status"))
        title = str(todo.get("content") or "")
        facts.extend(
            (
                f"Task({todo_id})",
                f"Status({todo_id}, {status})",
                f"Title({todo_id}, {json.dumps(title)})",
            )
        )
    return tuple(facts)


def _cycle_nodes(graph: dict[str, set[str]]) -> set[str]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    cycles: set[str] = set()

    for start in graph:
        if color[start] != WHITE:
            continue
        stack: list[tuple[str, Any]] = [(start, iter(sorted(graph.get(start, set()))))]
        color[start] = GRAY
        path: list[str] = [start]

        while stack:
            node, children = stack[-1]
            try:
                child = next(children)
                child_color = color.get(child, WHITE)
                if child_color == WHITE:
                    color[child] = GRAY
                    path.append(child)
                    stack.append((child, iter(sorted(graph.get(child, set())))))
                elif child_color == GRAY:
                    try:
                        idx = path.index(child)
                        cycles.update(path[idx:])
                    except ValueError:
                        cycles.add(child)
            except StopIteration:
                color[node] = BLACK
                stack.pop()
                if path and path[-1] == node:
                    path.pop()

    return cycles


def _freeze_graph(graph: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    return {node: tuple(sorted(edges)) for node, edges in sorted(graph.items())}


def _warning(
    code: str,
    message: str,
    rule: str,
    *,
    task_id: str | None = None,
    blockers: tuple[str, ...] = (),
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        rule=rule,
        severity="warning",
        task_id=task_id,
        blockers=blockers,
    )
