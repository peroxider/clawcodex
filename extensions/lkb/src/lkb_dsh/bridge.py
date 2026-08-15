"""LKB → DeepSeek Harness bridge module.

Exposes the LKB Plan Graph as a dsh plugin surface: one `@service` class
(`ctx.lkb`) wrapping `LkbApplicationService`, plus model-facing `@tool`
functions an agent can call directly. LKB business code is untouched — this
module only wires the existing repository / dispatcher / application service
behind `dsh_bridge` decorators.

Configuration flows two ways:

- The `@service` class takes init args (`board_id`, `plan_id`, `actor`,
  `home`, `roles`) from the generated TS package's `cordis.yml` config.
- Module-level `@tool` functions reuse the active service instance when one
  was constructed in the same child process, and otherwise fall back to
  `LKB_BOARD_ID` / `LKB_PLAN_ID` / `LKB_ACTOR` / `LKB_HOME` environment
  variables (the file-backed store keeps both paths consistent).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from dsh_bridge import provide_method, service, tool

from lkb.application import LkbApplicationService
from lkb.commands import GraphCommand
from lkb.graph_types import PlanSnapshot
from lkb.json_store import BoardNotFoundError
from lkb.plan_graph import plan_command_dispatcher
from lkb.refs import plan_task_ref
from lkb.repository import get_repository

# Status string → handler kind, mirroring `_STATUS_KIND` in plan_graph.
_STATUS_KIND = {
    "pending": "reopen_task",
    "in_progress": "start_task",
    "completed": "complete_task",
    "deleted": "delete_task",
}


def _project(repo: Any, board_id: str, plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Snapshot → (tasks, board) projection, LKB-native shape.

    Mirrors the adapter's `_build_projection` without the ClawCodex host
    dependency: each task carries its base state, owner, dependency edges,
    and derived readiness; the board aggregates revision + counts.
    """
    snap = repo.load_snapshot(board_id)
    plan = PlanSnapshot.from_graph(snap)

    blocked_by_map: dict[str, list[str]] = {}
    blocks_map: dict[str, list[str]] = {}
    for edge in snap.edges.values():
        if edge.graph != plan_id or edge.type != "depends_on":
            continue
        blocked_by_map.setdefault(edge.source.id, []).append(edge.target.id)
        blocks_map.setdefault(edge.target.id, []).append(edge.source.id)

    tasks: dict[str, Any] = {}
    counts = {"ready": 0, "running": 0, "blocked": 0, "verified": 0, "needsRecheck": 0}
    for ref, node in snap.nodes.items():
        if ref.graph != plan_id or ref.kind != "task":
            continue
        payload = node.payload if isinstance(node.payload, dict) else {}
        derived_raw = str(payload.get("derived_status", "") or "")
        state = str(node.state or "pending")
        if derived_raw in ("needs_recheck", "needs_review"):
            derived = derived_raw
        elif state == "completed":
            derived = "verified"
        elif ref in plan.blocked_ids:
            derived = "blocked"
        elif state == "in_progress":
            derived = "running"
        else:
            derived = "ready"
        tasks[ref.id] = {
            "id": ref.id,
            "subject": node.title,
            "description": str(payload.get("description", "")),
            "activeForm": str(payload.get("activeForm", node.title)),
            "status": state,
            "derivedStatus": derived,
            "owner": node.owner,
            "blocks": sorted(blocks_map.get(ref.id, [])),
            "blockedBy": sorted(blocked_by_map.get(ref.id, [])),
            "metadata": dict(payload.get("metadata", {}) or {}),
        }
        if derived == "needs_recheck":
            counts["needsRecheck"] += 1
        elif derived in counts:
            counts[derived] += 1
    graph = snap.graphs.get(plan_id)
    metadata = graph.metadata if graph is not None else {}
    board = {
        "boardId": snap.board_id,
        "revision": snap.store_revision,
        "planId": plan_id,
        "planTitle": str(metadata.get("title") or plan_id),
        "planState": str(metadata.get("state") or "active"),
        "counts": counts,
    }
    return tasks, board


class _LkbCore:
    """Thin wrapper over the LKB application pipeline (repo → dispatcher → service)."""

    def __init__(self, board_id: str, plan_id: str, actor: str, home: str, roles: str) -> None:
        self.board_id = board_id
        self.plan_id = plan_id
        self.actor = actor
        self.roles = tuple(r for r in roles.split(",") if r) if roles else ()
        self._repo = get_repository(home=Path(home)) if home else get_repository()
        self._dispatcher = plan_command_dispatcher()
        self._service = LkbApplicationService(repository=self._repo)
        self._ensure_board()

    def _ensure_board(self) -> None:
        try:
            self._repo.load_snapshot(self.board_id)
        except BoardNotFoundError:
            self._repo._create_board_from_id(self.board_id)

    def execute(self, kind: str, payload: dict[str, Any], task_id: str = "") -> Any:
        routed = {**payload, "plan_id": self.plan_id}
        command = GraphCommand(
            command_id=f"dsh-{uuid.uuid4().hex[:12]}",
            board_id=self.board_id,
            actor=self.actor,
            kind=kind,
            primary_subject_ref=plan_task_ref(task_id, graph_id=self.plan_id) if task_id else None,
            payload=routed,
            reason=None,
            roles=self.roles,
        )
        return self._service.execute(command, validate=self._dispatcher.validate, apply=self._dispatcher.apply)

    def projection(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return _project(self._repo, self.board_id, self.plan_id)


# The service instance constructed by the bridge runtime, so module-level
# tools in the same child share its configuration.
_ACTIVE_CORE: _LkbCore | None = None


def _env_core() -> _LkbCore:
    global _ACTIVE_CORE
    if _ACTIVE_CORE is not None:
        return _ACTIVE_CORE
    return _LkbCore(
        board_id=os.environ.get("LKB_BOARD_ID", "main"),
        plan_id=os.environ.get("LKB_PLAN_ID", "plan"),
        actor=os.environ.get("LKB_ACTOR", "dsh-agent"),
        home=os.environ.get("LKB_HOME", ""),
        roles=os.environ.get("LKB_ROLES", ""),
    )


def _decision_payload(result: Any) -> dict[str, Any]:
    revision = result.revision_vector
    return {
        "decision": result.decision,
        "reason": result.reason,
        "commandId": result.command_id,
        "revision": dict(revision.revisions) if revision is not None else {},
    }


def _tool_payload(result: Any) -> dict[str, Any]:
    """Model-facing decision fields for @tool returns.

    The ToolRuntime enforces each tool's output schema against the returned
    value, so the tool surface carries only domain fields: `decision` plus
    `reason` (the denial explanation a model needs to recover, normalized to
    a string). RPC bookkeeping (`commandId`) and store versioning
    (`revision`) stay on the programmatic service API (`_decision_payload`).
    """
    return {
        "decision": result.decision,
        "reason": result.reason or "",
    }


@service(name="lkb")
@dataclass
class LkbService:
    """Plan Graph capability exposed as `ctx.lkb` through the bridge."""

    board_id: str
    plan_id: str = "plan"
    actor: str = "dsh-agent"
    home: str = ""
    roles: str = ""

    def __post_init__(self) -> None:
        global _ACTIVE_CORE
        self._core = _LkbCore(self.board_id, self.plan_id, self.actor, self.home, self.roles)
        _ACTIVE_CORE = self._core

    @provide_method(timeout_ms=10_000)
    def create_task(
        self,
        subject: str,
        description: str = "",
        active_form: str = "",
        metadata: Optional[dict] = None,
    ) -> dict:
        task_id = f"T-{uuid.uuid4().hex[:8]}"
        result = self._core.execute(
            "create_task",
            {
                "task_id": task_id,
                "subject": subject,
                "description": description,
                "activeForm": active_form or subject,
                "metadata": dict(metadata or {}),
            },
            task_id=task_id,
        )
        return {"task": {"id": task_id, "subject": subject}, **_decision_payload(result)}

    @provide_method(timeout_ms=5_000)
    def get_task(self, task_id: str) -> Optional[dict]:
        tasks, _board = self._core.projection()
        return tasks.get(task_id)

    @provide_method(timeout_ms=5_000)
    def list_tasks(self) -> dict:
        tasks, board = self._core.projection()
        return {"tasks": list(tasks.values()), "lkbBoard": board}

    @provide_method(timeout_ms=10_000)
    def claim_task(self, task_id: str) -> dict:
        result = self._core.execute("claim_task", {"task_id": task_id}, task_id=task_id)
        return {"taskId": task_id, "owner": self.actor, **_decision_payload(result)}

    @provide_method(timeout_ms=10_000)
    def update_task(self, task_id: str, status: str) -> dict:
        kind = _STATUS_KIND.get(status)
        if kind is None:
            raise ValueError(f"unsupported status {status!r}; expected one of {sorted(_STATUS_KIND)}")
        if kind == "start_task":
            # start_task requires owner == actor; claim first (idempotent).
            claim = self._core.execute("claim_task", {"task_id": task_id}, task_id=task_id)
            if claim.decision != "committed":
                return {"taskId": task_id, "status": status, **_decision_payload(claim)}
        result = self._core.execute(kind, {"task_id": task_id}, task_id=task_id)
        return {"taskId": task_id, "status": status, **_decision_payload(result)}

    @provide_method(timeout_ms=10_000)
    def add_dependency(self, task_id: str, depends_on: str) -> dict:
        result = self._core.execute(
            "add_dependency",
            {"task_id": task_id, "depends_on": depends_on},
            task_id=task_id,
        )
        return {"taskId": task_id, "dependsOn": depends_on, **_decision_payload(result)}

    @provide_method(timeout_ms=5_000)
    def board_view(self) -> dict:
        _tasks, board = self._core.projection()
        return board


# ---------------------------------------------------------------------------
# Model-facing tools (registered on the generated package's shared bridge).
# ---------------------------------------------------------------------------


@tool(
    name="lkb_create_task",
    description="Create a task in the LKB Plan Graph.",
    parameters={
        "subject": {"type": "string", "required": True},
        "description": {"type": "string"},
        "active_form": {"type": "string"},
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task": {"type": "object", "additionalProperties": True},
            "decision": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
)
def lkb_create_task(subject: str, description: str = "", active_form: str = "") -> dict:
    core = _env_core()
    task_id = f"T-{uuid.uuid4().hex[:8]}"
    result = core.execute(
        "create_task",
        {
            "task_id": task_id,
            "subject": subject,
            "description": description,
            "activeForm": active_form or subject,
            "metadata": {},
        },
        task_id=task_id,
    )
    return {"task": {"id": task_id, "subject": subject}, **_tool_payload(result)}


@tool(
    name="lkb_list_tasks",
    description="List tasks in the LKB Plan Graph with their derived readiness.",
    parameters={},
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tasks": {"type": "array"},
            "lkbBoard": {"type": "object", "additionalProperties": True},
        },
    },
)
def lkb_list_tasks() -> dict:
    tasks, board = _env_core().projection()
    return {"tasks": list(tasks.values()), "lkbBoard": board}


@tool(
    name="lkb_update_task",
    description="Transition a task's status in the LKB Plan Graph.",
    parameters={
        "task_id": {"type": "string", "required": True},
        "status": {"type": "string", "required": True},
    },
    output_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "taskId": {"type": "string"},
            "status": {"type": "string"},
            "decision": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
)
def lkb_update_task(task_id: str, status: str) -> dict:
    kind = _STATUS_KIND.get(status)
    if kind is None:
        raise ValueError(f"unsupported status {status!r}; expected one of {sorted(_STATUS_KIND)}")
    core = _env_core()
    if kind == "start_task":
        claim = core.execute("claim_task", {"task_id": task_id}, task_id=task_id)
        if claim.decision != "committed":
            return {"taskId": task_id, "status": status, **_tool_payload(claim)}
    result = core.execute(kind, {"task_id": task_id}, task_id=task_id)
    return {"taskId": task_id, "status": status, **_tool_payload(result)}


@tool(
    name="lkb_board_view",
    description="Read the LKB board aggregate (counts, readiness, suggested actions).",
    parameters={},
    output_schema={
        "type": "object",
        "additionalProperties": True,
        "properties": {},
    },
)
def lkb_board_view() -> dict:
    _tasks, board = _env_core().projection()
    return board


if __name__ == "__main__":  # pragma: no cover
    # Local smoke test without the bridge: exercise the service directly.
    import tempfile

    home = tempfile.mkdtemp(prefix="lkb-dsh-")
    svc = LkbService(board_id="smoke", home=home)
    created = svc.create_task(subject="smoke task", description="via LkbService")
    print("create:", created["decision"], created["task"]["id"])
    listed = svc.list_tasks()
    print("list:", [t.get("id") for t in listed["tasks"]])
    updated = svc.update_task(created["task"]["id"], "in_progress")
    print("update:", updated["decision"])
    completed = svc.update_task(created["task"]["id"], "completed")
    print("complete:", completed["decision"])
    board = svc.board_view()
    print("board keys:", sorted(board)[:8])
    print("home:", home)