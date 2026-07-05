"""Synchronous Logical Kanban foundation service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .context_adapter import active_blockers, build_facts_snapshot, dependency_closure
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
        return build_facts_snapshot(context)

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

        snapshot = self.snapshot(context)
        cyclic_dependencies = sorted(
            {task_id, *dependency_closure(snapshot, task_id)} & snapshot.cycle_task_ids
        )
        if cyclic_dependencies:
            issue = ValidationIssue(
                code="cyclic_dependency_blocks_readiness",
                message=(
                    f"Task {task_id} cannot enter in_progress because its readiness "
                    f"depends on a cyclic dependency chain: {', '.join(cyclic_dependencies)}."
                ),
                rule="LKB-CYCLE-001",
                task_id=task_id,
                blockers=tuple(cyclic_dependencies),
                repair_suggestions=(
                    RepairSuggestion(
                        action="remove_dependency_cycle",
                        target=task_id,
                        message="Remove or rewrite one dependency edge in the cycle.",
                    ),
                ),
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue, *snapshot.warnings),
                snapshot_hash=proposal.snapshot_hash,
                proof_trace=(
                    {
                        "rule": "LKB-CYCLE-001",
                        "premises": [
                            f"Cycle({cycle_task_id})" for cycle_task_id in cyclic_dependencies
                        ],
                        "conclusion": f"NotReady({task_id})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        blockers = list(active_blockers(snapshot, task_id))
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
            issues=(issue, *snapshot.warnings),
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
