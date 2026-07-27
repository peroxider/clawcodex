"""Unified Read Model for the LKB board (spec §8.5, Phase 7).

:class:`LkbBoardView` is the UI-agnostic projection consumed by
``/lkb board``, ``/lkb status``, TaskList top-level summary, the REPL
task snapshot, and the TUI.  Renderers must NEVER read ``board.json`` or
re-derive domain rules - they only consume this view.

Badge priority is fixed (spec §8.3):
``validation_failed > needs_review > needs_recheck > blocked > running
> ready > verified``.  A historically-completed task that is now stale
shows ``NEEDS_RECHECK`` even when it also has active blockers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph_types import NodeRef, PlanSnapshot
from .json_store import BoardEnvelope

__all__ = [
    "LkbBoardRow",
    "LkbBoardSummary",
    "LkbBoardIssue",
    "LkbBoardView",
    "build_board_view",
    "BADGE_PRIORITY",
]

BADGE_PRIORITY = (
    "validation_failed",
    "needs_review",
    "needs_recheck",
    "blocked",
    "running",
    "ready",
    "verified",
)

_BADGE_LABEL = {
    "validation_failed": "VALIDATION_FAILED",
    "needs_review": "NEEDS_REVIEW",
    "needs_recheck": "NEEDS_RECHECK",
    "blocked": "BLOCKED",
    "running": "RUNNING",
    "ready": "READY",
    "verified": "VERIFIED",
}


@dataclass(frozen=True)
class LkbBoardRow:
    task_id: str
    title: str
    owner: str
    base_status: str
    badge: str
    active_blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class LkbBoardSummary:
    ready: int = 0
    running: int = 0
    blocked: int = 0
    needs_recheck: int = 0
    issues: int = 0


@dataclass(frozen=True)
class LkbBoardIssue:
    task_id: str
    message: str


@dataclass(frozen=True)
class LkbBoardView:
    board_id: str
    display_name: str
    store_revision: int
    plan_id: str
    plan_title: str
    plan_state: str
    plan_revision: int
    summary: LkbBoardSummary
    rows: tuple[LkbBoardRow, ...] = ()
    issues: tuple[LkbBoardIssue, ...] = ()
    suggested_actions: tuple[str, ...] = ()


def _badge_for(
    node: dict[str, Any],
    ref: NodeRef,
    plan: PlanSnapshot,
) -> str:
    payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
    derived = str(payload.get("derived_status", "") or "")
    if derived == "needs_recheck":
        return "needs_recheck"
    if derived == "needs_review":
        return "needs_review"
    state = str(node.get("state", "pending"))
    if state == "completed":
        return "verified"
    if ref in plan.blocked_ids:
        return "blocked"
    if state == "in_progress":
        return "running"
    return "ready"


def build_board_view(
    envelope: BoardEnvelope,
    plan_id: str = "plan",
) -> LkbBoardView:
    """Project an envelope into a UI-agnostic :class:`LkbBoardView`."""
    snapshot = envelope.build_graph_snapshot()
    plan = PlanSnapshot.from_graph(snapshot)

    board_dict = envelope.board if isinstance(envelope.board, dict) else {}
    board_id = str(board_dict.get("board_id", ""))
    display_name = str(board_dict.get("display_name", board_id))
    plan_graph = envelope.graphs.get(plan_id, {})
    plan_revision = int(plan_graph.get("revision", 0))
    plan_metadata = plan_graph.get("plan") if isinstance(plan_graph.get("plan"), dict) else {}

    rows: list[LkbBoardRow] = []
    issues: list[LkbBoardIssue] = []
    counts = {"ready": 0, "running": 0, "blocked": 0, "needs_recheck": 0}

    # Sort rows by task_id for stable display.
    plan_nodes = sorted(
        (
            (NodeRef.from_str(str(n.get("ref", ""))), n)
            for n in envelope.nodes.values()
            if str(n.get("ref", "")).startswith(f"{plan_id}:task:")
        ),
        key=lambda kv: kv[0].id,
    )

    for ref, node in plan_nodes:
        badge = _badge_for(node, ref, plan)
        blockers = plan.active_blockers.get(ref, ())
        blocker_ids = tuple(b.id for b in blockers)
        rows.append(
            LkbBoardRow(
                task_id=ref.id,
                title=str(node.get("title", "")),
                owner=str(node.get("owner") or "-"),
                base_status=str(node.get("state", "pending")),
                badge=badge,
                active_blockers=blocker_ids,
            )
        )
        if badge in counts:
            counts[badge] += 1
        if badge == "blocked":
            issues.append(
                LkbBoardIssue(
                    task_id=ref.id,
                    message=f"{ref.id} waits for {', '.join(blocker_ids) if blocker_ids else 'unknown'}",
                )
            )
        if badge == "needs_recheck":
            cause = (
                (node.get("payload") or {}).get("invalidation_cause")
                if isinstance(node.get("payload"), dict)
                else None
            )
            issues.append(
                LkbBoardIssue(
                    task_id=ref.id,
                    message=f"{ref.id} needs recheck" + (f" (cause: {cause})" if cause else ""),
                )
            )

    suggested = _suggested_actions(rows, plan)
    return LkbBoardView(
        board_id=board_id,
        display_name=display_name,
        store_revision=envelope.store_revision,
        plan_id=plan_id,
        plan_title=str(plan_metadata.get("title") or plan_id),
        plan_state=str(plan_metadata.get("state") or "active"),
        plan_revision=plan_revision,
        summary=LkbBoardSummary(
            ready=counts["ready"],
            running=counts["running"],
            blocked=counts["blocked"],
            needs_recheck=counts["needs_recheck"],
            issues=len(issues),
        ),
        rows=tuple(rows),
        issues=tuple(issues),
        suggested_actions=tuple(suggested),
    )


def _suggested_actions(rows: list[LkbBoardRow], plan: PlanSnapshot) -> list[str]:
    actions: list[str] = []
    ready = [r for r in rows if r.badge == "ready"]
    if ready:
        actions.append(f"claim {ready[0].task_id}")
    for row in rows:
        if row.badge == "needs_recheck":
            actions.append(f"revalidate {row.task_id}")
    for row in rows:
        if row.badge in ("blocked", "needs_recheck", "needs_review", "validation_failed"):
            actions.append(f"explain {row.task_id}")
            break  # one explain suggestion is enough
    return actions
