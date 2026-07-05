"""Synchronous Logical Kanban foundation service."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
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
        if proposal.change.kind == "create_task":
            return self._accepted(
                proposal,
                derived_facts=(
                    f"Task({proposal.change.payload.get('taskId')})",
                    f"Pending({proposal.change.payload.get('taskId')})",
                    f"Status({proposal.change.payload.get('taskId')}, pending)",
                ),
                proof_trace=(
                    {
                        "rule": "LKB-CREATE-001",
                        "premises": ["CreateTaskProposal"],
                        "conclusion": "Create structural task facts.",
                        "solverVersion": self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == "legacy_todo_replace_all":
            return self._validate_legacy_todo_replace_all(proposal, context)
        if proposal.change.kind == "transition_status":
            return self._validate_status_transition(proposal, context)
        if proposal.change.kind in {
            "update_task_fields",
            "delete_task",
            "add_dependency",
            "remove_dependency",
        }:
            return self._validate_structural_task_change(proposal, context)
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
                derived_facts=validation.derived_facts,
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

    def _validate_legacy_todo_replace_all(
        self,
        proposal: Proposal,
        context: "ToolContext",
    ) -> ValidationRun:
        todos = proposal.change.payload.get("todos")
        if not isinstance(todos, list):
            issue = ValidationIssue(
                code="malformed_legacy_todo_write",
                message="TodoWrite payload must contain a todos array.",
                rule="LKB-TODOWRITE-COMPAT-001",
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue,),
                snapshot_hash=proposal.snapshot_hash,
                proof_trace=(
                    {
                        "rule": "LKB-TODOWRITE-COMPAT-001",
                        "premises": ["Not(Array(todos))"],
                        "conclusion": "DenyCommit",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        status_counts = {"pending": 0, "in_progress": 0, "completed": 0}
        malformed_indexes: list[int] = []
        in_progress_ids: list[str] = []
        derived_facts: list[str] = []
        for index, todo in enumerate(todos):
            todo_id = f"todo:{index}"
            if not isinstance(todo, dict) or todo.get("status") not in status_counts:
                malformed_indexes.append(index)
                continue
            status = str(todo["status"])
            status_counts[status] += 1
            if status == "in_progress":
                in_progress_ids.append(todo_id)
            derived_facts.extend((f"Task({todo_id})", f"Status({todo_id}, {status})"))

        if malformed_indexes:
            issue = ValidationIssue(
                code="malformed_legacy_todo_write",
                message=(
                    "TodoWrite contains malformed todos at indexes: "
                    f"{', '.join(str(i) for i in malformed_indexes)}."
                ),
                rule="LKB-TODOWRITE-COMPAT-001",
                blockers=tuple(f"todo:{i}" for i in malformed_indexes),
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue,),
                snapshot_hash=proposal.snapshot_hash,
                proof_trace=(
                    {
                        "rule": "LKB-TODOWRITE-COMPAT-001",
                        "premises": [f"Malformed(todo:{i})" for i in malformed_indexes],
                        "conclusion": "DenyCommit",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        total = len(todos)
        derived_facts.append(
            "TodoProgress("
            f"total={total}, "
            f"pending={status_counts['pending']}, "
            f"in_progress={status_counts['in_progress']}, "
            f"completed={status_counts['completed']}"
            ")"
        )
        if total > 0 and status_counts["completed"] == total:
            derived_facts.append("AllLegacyTodosCompleted")

        runtime = getattr(context, "logical_kanban", None)
        if bool(getattr(runtime, "strict_logical_todo_enabled", False)) and len(
            in_progress_ids
        ) > 1:
            issue = ValidationIssue(
                code="multiple_in_progress_legacy_todo_write",
                message=(
                    "TodoWrite cannot set multiple in_progress todos while strict "
                    f"logical todo mode is enabled: {', '.join(in_progress_ids)}."
                ),
                rule="LKB-TODOWRITE-COMPAT-002",
                blockers=tuple(in_progress_ids),
                repair_suggestions=(
                    RepairSuggestion(
                        action="keep_single_in_progress",
                        target=in_progress_ids[0],
                        message="Leave only one todo in_progress and keep the others pending.",
                    ),
                ),
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue,),
                snapshot_hash=proposal.snapshot_hash,
                derived_facts=tuple(derived_facts),
                proof_trace=(
                    {
                        "rule": "LKB-TODOWRITE-COMPAT-002",
                        "premises": [f"Doing({todo_id})" for todo_id in in_progress_ids],
                        "conclusion": "DenyCommit",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        return self._accepted(
            proposal,
            derived_facts=tuple(derived_facts),
            proof_trace=(
                {
                    "rule": "LKB-TODOWRITE-COMPAT-ALLOW",
                    "premises": [
                        "LegacyTodoWriteCompatibilityMode",
                        f"InProgressCount({status_counts['in_progress']})",
                    ],
                    "conclusion": "Allow legacy TodoWrite replacement.",
                    "solverVersion": self.solver_version,
                },
            ),
        )

    def _validate_status_transition(
        self,
        proposal: Proposal,
        context: "ToolContext",
    ) -> ValidationRun:
        payload = proposal.change.payload
        task_id = payload.get("taskId")
        target_status = payload.get("status")
        if not isinstance(task_id, str) or target_status not in {
            "pending",
            "in_progress",
            "completed",
        }:
            return self._accepted(proposal)

        task = (getattr(context, "tasks", {}) or {}).get(task_id)
        if not isinstance(task, dict):
            issue = ValidationIssue(
                code="task_not_found",
                message=f"Task {task_id} does not exist.",
                rule="LKB-TRANSITION-001",
                task_id=task_id,
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue,),
                snapshot_hash=proposal.snapshot_hash,
                proof_trace=(
                    {
                        "rule": "LKB-TRANSITION-001",
                        "premises": [f"Not(Task({task_id}))"],
                        "conclusion": f"Not(CanMoveTo({task_id}, {target_status}))",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        current_status = task.get("status")
        snapshot = self.snapshot(context)
        if current_status == target_status:
            return self._accepted(
                proposal,
                derived_facts=(f"NoStatusChange({task_id})",),
                proof_trace=(
                    {
                        "rule": "LKB-NOOP-001",
                        "premises": [f"Status({task_id}, {target_status})"],
                        "conclusion": f"NoStatusChange({task_id})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        if target_status == "pending" and current_status == "completed":
            return self._accepted(
                proposal,
                derived_facts=(f"Reopened({task_id})",),
                proof_trace=(
                    {
                        "rule": "LKB-REOPEN-001",
                        "premises": [f"Status({task_id}, completed)", "ExplicitReopen"],
                        "conclusion": f"CanMoveTo({task_id}, pending)",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        if target_status == "completed" and self._strict_acceptance_enabled(
            context, task, payload
        ):
            if not self._has_acceptance_proof(task, payload):
                issue = ValidationIssue(
                    code="completed_requires_acceptance_proof",
                    message=(
                        f"Task {task_id} cannot enter completed because strict "
                        "acceptance is enabled and no acceptance proof is present."
                    ),
                    rule="LKB-ACCEPTANCE-001",
                    task_id=task_id,
                    repair_suggestions=(
                        RepairSuggestion(
                            action="add_acceptance_proof",
                            target=task_id,
                            message="Attach metadata.lkb.acceptance_proof before completing the task.",
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
                            "rule": "LKB-ACCEPTANCE-001",
                            "premises": [
                                f"StrictAcceptance({task_id})",
                                f"Not(HasAcceptanceProof({task_id}))",
                            ],
                            "conclusion": f"Not(CanMoveTo({task_id}, completed))",
                            "solverVersion": self.solver_version,
                        },
                    ),
                )
            return self._accepted(
                proposal,
                derived_facts=(
                    f"HasAcceptanceProof({task_id})",
                    f"CanMoveTo({task_id}, completed)",
                ),
                proof_trace=(
                    {
                        "rule": "LKB-ACCEPTANCE-001",
                        "premises": [
                            f"StrictAcceptance({task_id})",
                            f"HasAcceptanceProof({task_id})",
                        ],
                        "conclusion": f"CanMoveTo({task_id}, completed)",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        if target_status != "in_progress":
            return self._accepted(
                proposal,
                derived_facts=(f"CanMoveTo({task_id}, {target_status})",),
            )

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
                derived_facts=(
                    f"Cycle({task_id})",
                    f"NotReady({task_id})",
                    f"Not(CanMoveTo({task_id}, in_progress))",
                ),
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
                derived_facts=(
                    f"Ready({task_id})",
                    f"CanMoveTo({task_id}, in_progress)",
                ),
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
            derived_facts=(
                f"Blocked({task_id})",
                f"Not(CanMoveTo({task_id}, in_progress))",
            ),
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

    def _validate_structural_task_change(
        self,
        proposal: Proposal,
        context: "ToolContext",
    ) -> ValidationRun:
        payload = proposal.change.payload
        task_id = payload.get("taskId")
        if isinstance(task_id, str) and task_id not in (getattr(context, "tasks", {}) or {}):
            issue = ValidationIssue(
                code="task_not_found",
                message=f"Task {task_id} does not exist.",
                rule="LKB-STRUCTURE-001",
                task_id=task_id,
            )
            return ValidationRun(
                validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                status="denied",
                issues=(issue,),
                snapshot_hash=proposal.snapshot_hash,
                proof_trace=(
                    {
                        "rule": "LKB-STRUCTURE-001",
                        "premises": [f"Not(Task({task_id}))"],
                        "conclusion": "DenyCommit",
                        "solverVersion": self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == "delete_task":
            return self._accepted(
                proposal,
                derived_facts=(f"CanDelete({task_id})", "CascadeDependencyCleanupAfterValidation"),
                proof_trace=(
                    {
                        "rule": "LKB-DELETE-001",
                        "premises": [f"Task({task_id})"],
                        "conclusion": f"CanDelete({task_id})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == "update_task_fields":
            return self._accepted(
                proposal,
                derived_facts=(f"CanUpdateTaskFields({task_id})",),
                proof_trace=(
                    {
                        "rule": "LKB-FIELDS-001",
                        "premises": [f"Task({task_id})"],
                        "conclusion": f"CanUpdateTaskFields({task_id})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == "add_dependency":
            preview = self._preview_dependency_context(context, payload)
            snapshot = self.snapshot(preview)  # type: ignore[arg-type]
            task_cycle = (
                sorted(snapshot.cycle_task_ids)
                if not isinstance(task_id, str)
                else sorted(
                    {task_id, *dependency_closure(snapshot, task_id)} & snapshot.cycle_task_ids
                )
            )
            if task_cycle:
                issue = ValidationIssue(
                    code="dependency_cycle_denied",
                    message=(
                        "Dependency update would create a cycle involving: "
                        f"{', '.join(task_cycle)}."
                    ),
                    rule="LKB-DEPENDENCY-002",
                    task_id=task_id if isinstance(task_id, str) else None,
                    blockers=tuple(task_cycle),
                    repair_suggestions=(
                        RepairSuggestion(
                            action="remove_dependency_cycle",
                            target=task_id if isinstance(task_id, str) else None,
                            message="Remove one reciprocal or transitive dependency edge.",
                        ),
                    ),
                )
                return ValidationRun(
                    validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
                    proposal_id=proposal.proposal_id,
                    status="denied",
                    issues=(issue, *snapshot.warnings),
                    snapshot_hash=snapshot.hash,
                    derived_facts=tuple(f"Cycle({cycle_task_id})" for cycle_task_id in task_cycle),
                    proof_trace=(
                        {
                            "rule": "LKB-DEPENDENCY-002",
                            "premises": [
                                f"Cycle({cycle_task_id})" for cycle_task_id in task_cycle
                            ],
                            "conclusion": "DenyCommit",
                            "solverVersion": self.solver_version,
                        },
                    ),
                )
            return self._accepted(
                proposal,
                derived_facts=(f"CanMutateDependencies({task_id})",),
                proof_trace=(
                    {
                        "rule": "LKB-DEPENDENCY-001",
                        "premises": [f"Task({task_id})", "NoDependencyCycleAfterMutation"],
                        "conclusion": f"CanMutateDependencies({task_id})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )
        return self._accepted(
            proposal,
            derived_facts=(f"CanMutateDependencies({task_id})",),
            proof_trace=(
                {
                    "rule": "LKB-DEPENDENCY-001",
                    "premises": [f"Task({task_id})"],
                    "conclusion": f"CanMutateDependencies({task_id})",
                    "solverVersion": self.solver_version,
                },
            ),
        )

    def _preview_dependency_context(
        self,
        context: "ToolContext",
        payload: dict[str, Any],
    ) -> Any:
        task_id = payload.get("taskId")
        tasks = {
            key: {
                **dict(value),
                "blocks": list((value or {}).get("blocks") or []),
                "blockedBy": list((value or {}).get("blockedBy") or []),
                "metadata": dict((value or {}).get("metadata") or {}),
            }
            for key, value in (getattr(context, "tasks", {}) or {}).items()
            if isinstance(value, dict)
        }
        task = tasks.get(task_id) if isinstance(task_id, str) else None
        if task is not None:
            for rel_field, input_key in (("blocks", "addBlocks"), ("blockedBy", "addBlockedBy")):
                ids = payload.get(input_key)
                if isinstance(ids, list):
                    cur = list(task.get(rel_field) or [])
                    for item in ids:
                        if isinstance(item, str) and item not in cur:
                            cur.append(item)
                    task[rel_field] = cur
        return SimpleNamespace(tasks=tasks, todos=getattr(context, "todos", ()))

    def _accepted(
        self,
        proposal: Proposal,
        *,
        proof_trace: tuple[dict[str, Any], ...] | None = None,
        derived_facts: tuple[str, ...] = (),
    ) -> ValidationRun:
        return ValidationRun(
            validation_id=f"lkb-val-{uuid.uuid4().hex[:12]}",
            proposal_id=proposal.proposal_id,
            status="accepted",
            snapshot_hash=proposal.snapshot_hash,
            derived_facts=derived_facts,
            proof_trace=proof_trace
            or (
                {
                    "rule": "LKB-FOUNDATION-ALLOW",
                    "conclusion": "No foundation rule denied this change.",
                    "solverVersion": self.solver_version,
                },
            ),
        )

    def _strict_acceptance_enabled(
        self,
        context: "ToolContext",
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        runtime = getattr(context, "logical_kanban", None)
        if bool(getattr(runtime, "strict_acceptance_enabled", False)):
            return True
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        lkb = metadata.get("lkb") if isinstance(metadata, dict) else {}
        if isinstance(lkb, dict) and bool(lkb.get("strict_acceptance")):
            return True
        incoming = payload.get("metadata")
        incoming_lkb = incoming.get("lkb") if isinstance(incoming, dict) else {}
        return isinstance(incoming_lkb, dict) and bool(incoming_lkb.get("strict_acceptance"))

    def _has_acceptance_proof(
        self,
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        lkb = metadata.get("lkb") if isinstance(metadata, dict) else {}
        if isinstance(lkb, dict) and bool(lkb.get("acceptance_proof")):
            return True
        incoming = payload.get("metadata")
        incoming_lkb = incoming.get("lkb") if isinstance(incoming, dict) else {}
        return isinstance(incoming_lkb, dict) and bool(incoming_lkb.get("acceptance_proof"))
