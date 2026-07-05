"""Synchronous Logical Kanban foundation service."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any

from .types import (
    CommitResult,
    FactsSnapshot,
    Proposal,
    ProposedChange,
    RepairSuggestion,
    ValidationIssue,
    ValidationRun,
)

if TYPE_CHECKING:
    from clawcodex_ext.tool_system.context import ToolContext


class LogicalKanbanService:
    """Internal propose/validate/commit service for task-state changes."""

    solver_version = "lkb-foundation-sync-v1"

    def snapshot(self, context: "ToolContext") -> FactsSnapshot:
        todos = tuple(dict(t) for t in getattr(context, "todos", []) or [])
        tasks = {
            task_id: dict(task)
            for task_id, task in (getattr(context, "tasks", {}) or {}).items()
        }
        payload = {"todos": todos, "tasks": tasks}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return FactsSnapshot(todos=todos, tasks=tasks, hash=f"sha256:{digest}")

    def propose(self, change: ProposedChange, context: "ToolContext") -> Proposal:
        snapshot = self.snapshot(context)
        return Proposal(
            proposal_id=f"lkb-prop-{uuid.uuid4().hex[:12]}",
            change=change,
            snapshot_hash=snapshot.hash,
        )

    def validate(self, proposal: Proposal, context: "ToolContext") -> ValidationRun:
        if proposal.change.kind == "task_update":
            return self._validate_task_update(proposal, context)
        return self._accepted(proposal)

    def commit(
        self,
        proposal: Proposal,
        validation: ValidationRun,
        context: "ToolContext",
    ) -> CommitResult:
        if validation.accepted:
            return CommitResult(
                committed=True,
                proposal_id=proposal.proposal_id,
                validation_id=validation.validation_id,
            )
        return CommitResult(
            committed=False,
            proposal_id=proposal.proposal_id,
            validation_id=validation.validation_id,
            reason={
                "code": validation.issues[0].code if validation.issues else "validation_denied",
                "validation": validation.to_dict(),
            },
        )

    def run(
        self,
        change: ProposedChange,
        context: "ToolContext",
    ) -> tuple[Proposal, ValidationRun, CommitResult]:
        proposal = self.propose(change, context)
        validation = self.validate(proposal, context)
        commit = self.commit(proposal, validation, context)
        return proposal, validation, commit

    def _validate_task_update(
        self,
        proposal: Proposal,
        context: "ToolContext",
    ) -> ValidationRun:
        payload = proposal.change.payload
        task_id = payload.get("taskId")
        target_status = payload.get("status")
        if target_status != "in_progress" or not isinstance(task_id, str):
            return self._accepted(proposal)

        task = (getattr(context, "tasks", {}) or {}).get(task_id)
        if not isinstance(task, dict):
            return self._accepted(proposal)

        blockers = self._active_blockers(task, context)
        if not blockers:
            return self._accepted(
                proposal,
                proof_trace=(
                    {
                        "rule": "LKB-001",
                        "premises": [f"ActiveBlockers({task_id}) = []"],
                        "conclusion": f"CanMoveTo({task_id}, in_progress)",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        issue = ValidationIssue(
            code="blocked_task_cannot_enter_in_progress",
            message=(
                f"Task {task_id} cannot enter in_progress because active "
                f"blockers remain: {', '.join(blockers)}."
            ),
            rule="LKB-001",
            task_id=task_id,
            blockers=tuple(blockers),
            repair_suggestions=tuple(
                RepairSuggestion(
                    action="complete_prerequisite",
                    target=blocker,
                    message=f"Complete blocker {blocker} before starting {task_id}.",
                )
                for blocker in blockers
            ),
        )
        return ValidationRun(
            validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            status="denied",
            issues=(issue,),
            snapshot_hash=proposal.snapshot_hash,
            proof_trace=tuple(
                {
                    "rule": "LKB-001",
                    "premises": [
                        f"BlockedBy({task_id}, {blocker})",
                        f"NotCompleted({blocker})",
                    ],
                    "conclusion": f"Blocked({task_id})",
                }
                for blocker in blockers
            ),
        )

    def _accepted(
        self,
        proposal: Proposal,
        *,
        proof_trace: tuple[dict[str, Any], ...] | None = None,
    ) -> ValidationRun:
        return ValidationRun(
            validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            status="accepted",
            snapshot_hash=proposal.snapshot_hash,
            proof_trace=proof_trace
            or (
                {
                    "rule": "LKB-FOUNDATION-ALLOW",
                    "conclusion": "No foundation rule denied this change.",
                    "solverVersion": self.solver_version,
                },
            ),
        )

    @staticmethod
    def _active_blockers(task: dict[str, Any], context: "ToolContext") -> list[str]:
        tasks = getattr(context, "tasks", {}) or {}
        active: list[str] = []
        for blocker_id in task.get("blockedBy") or []:
            blocker = tasks.get(blocker_id)
            if not isinstance(blocker, dict) or blocker.get("status") != "completed":
                active.append(str(blocker_id))
        return active
