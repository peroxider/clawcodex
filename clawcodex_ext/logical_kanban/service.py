"""Synchronous Logical Kanban foundation service."""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from .ambiguity_detector import AmbiguityDetector
from .commit_gate_fuzzy import aggregate_world_results, commit_gate_fuzzy_check
from .context_adapter import active_blockers, build_facts_snapshot, dependency_closure
from .fuzzy_types import AggregationDecision, CommitDecision, MultiWorldResult
from .ir_hash import canonical_hash
from .multiworld_validator import MultiWorldValidator
from .rule_engine import Layer1RuleEngine
from .runtime import get_logical_kanban
from .truth_maintenance import TruthMaintenanceSystem
from .world_generator import WorldGenerator
from .types import (
    CommitResult,
    FactsSnapshot,
    Proposal,
    ProposedChange,
    RepairSuggestion,
    ValidationIssue,
    ValidationResult,
    ValidationRun,
)

if TYPE_CHECKING:
    from clawcodex_ext.tool_system.context import ToolContext
    from .fuzzy_types import Clarification, World
    from .ir import CanonicalAssertion
    from .truth_maintenance import AssumptionRecord


_LAYER1_RULESET = {
    "name": "lkb-layer1-mvp",
    "version": "1.0.0",
    "engine": "layer1-python",
    "rules": [
        {"id": "R-001", "description": "Blocked(T) when active prerequisites remain"},
        {"id": "R-002", "description": "Blocked task cannot enter in_progress"},
        {"id": "R-003", "description": "Ready(T) when pending and not blocked"},
        {"id": "R-004", "description": "CanMoveTo(T, in_progress) when Ready(T)"},
        {"id": "R-005", "description": "Done requires acceptance proof in strict mode"},
        {"id": "R-006", "description": "Cyclic dependency invalidates readiness"},
    ],
}
_RULESET_HASH = canonical_hash(_LAYER1_RULESET)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class LogicalKanbanService:
    """Internal propose/validate/commit service for task-state changes."""

    solver_version = "lkb-foundation-sync-v1"

    def __init__(self) -> None:
        self.engine = Layer1RuleEngine()

    def snapshot(self, context: "ToolContext") -> FactsSnapshot:
        return build_facts_snapshot(context)

    def propose(self, change: ProposedChange, context: "ToolContext") -> Proposal:
        snapshot = self.snapshot(context)
        return Proposal(
            proposal_id=_new_id("P-"),
            change=change,
            snapshot_hash=snapshot.hash,
        )

    def validate(self, proposal: Proposal, context: "ToolContext") -> ValidationRun:
        start = time.perf_counter()
        run = self._do_validate(proposal, context)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return replace(run, duration_ms=max(duration_ms, 0))

    def _do_validate(self, proposal: Proposal, context: "ToolContext") -> ValidationRun:
        if proposal.change.kind == "create_task":
            task_id = proposal.change.payload.get("taskId")
            return self._accepted(
                proposal,
                task_id=task_id if isinstance(task_id, str) else None,
                derived_facts=(
                    f"Task({task_id})",
                    f"Pending({task_id})",
                    f"Status({task_id}, pending)",
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
        if proposal.change.kind == "propose_assertion":
            return self._validate_propose_assertion(proposal, context)
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
                validation_run_id=validation.validation_run_id,
                derived_facts=validation.derived_facts,
            )
        return CommitResult(
            committed=False,
            proposal_id=proposal.proposal_id,
            validation_run_id=validation.validation_run_id,
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

    def evaluate_assertion(
        self,
        text: str,
        base_assertion: "CanonicalAssertion",
        *,
        assertion_id: str | None = None,
        context_facts: tuple[str, ...] = (),
    ) -> MultiWorldResult:
        """Detect ambiguities in ``text`` and generate possible worlds.

        This is the entry point for the F-134 fuzzy input layer.  It runs the
        symbol-based ambiguity detector, builds one CanonicalAssertion per
        consistent interpretation, and returns a MultiWorldResult.
        """
        from .ir import CanonicalAssertion

        assertion_id = assertion_id or _new_id("A-")
        if not isinstance(base_assertion, CanonicalAssertion):
            raise TypeError("base_assertion must be a CanonicalAssertion")
        detector = AmbiguityDetector()
        report = detector.detect(
            text,
            assertion_id=assertion_id,
            context_facts=context_facts,
        )
        worlds = WorldGenerator().generate(report, base_assertion)
        return MultiWorldResult(
            assertion_id=assertion_id,
            ambiguity_report=report,
            worlds=tuple(worlds),
        )

    def validate_assertion_proposal(
        self,
        multi_world_result: MultiWorldResult,
        context: "ToolContext",
        *,
        target_task_id: str | None = None,
        target_status: str | None = None,
        is_irreversible: bool = True,
    ) -> tuple[AggregationDecision, CommitDecision]:
        """Validate every world and decide whether the assertion may commit.

        Returns the aggregation decision and the final fuzzy commit decision.
        """
        snapshot = self.snapshot(context)
        validator = MultiWorldValidator(self.engine)
        world_results = validator.validate(
            list(multi_world_result.worlds),
            snapshot,
            target_task_id=target_task_id,
            target_status=target_status,
        )
        aggregation = aggregate_world_results(world_results)
        commit_decision = commit_gate_fuzzy_check(
            list(multi_world_result.worlds),
            world_results,
            multi_world_result.ambiguity_report,
            is_irreversible=is_irreversible,
        )
        return aggregation, commit_decision

    def _validate_propose_assertion(
        self,
        proposal: Proposal,
        context: "ToolContext",
    ) -> ValidationRun:
        """Validate a natural-language assertion proposal through the fuzzy layer."""
        from .ir import CanonicalAssertion

        payload = proposal.change.payload
        text = payload.get("text") if isinstance(payload, dict) else ""
        base_assertion = payload.get("baseAssertion")
        target_task_id = payload.get("targetTaskId")
        target_status = payload.get("targetStatus")

        if not isinstance(text, str) or not text:
            issue = ValidationIssue(
                code="missing_assertion_text",
                message="Assertion proposal must include a non-empty text field.",
                rule="LKB-ASSERTION-001",
            )
            return self._denied(proposal, issues=(issue,))

        if not isinstance(base_assertion, CanonicalAssertion):
            issue = ValidationIssue(
                code="missing_base_assertion",
                message="Assertion proposal must include a base CanonicalAssertion.",
                rule="LKB-ASSERTION-002",
            )
            return self._denied(proposal, issues=(issue,))

        multi_world = self.evaluate_assertion(
            text,
            base_assertion,
            assertion_id=payload.get("assertionId"),
            context_facts=tuple(payload.get("contextFacts", [])),
        )
        aggregation, commit_decision = self.validate_assertion_proposal(
            multi_world,
            context,
            target_task_id=target_task_id if isinstance(target_task_id, str) else None,
            target_status=target_status if isinstance(target_status, str) else None,
            is_irreversible=bool(payload.get("isIrreversible", True)),
        )

        if not commit_decision.commit:
            issue = ValidationIssue(
                code=commit_decision.reason,
                message=commit_decision.human_message.get(
                    "en", "Fuzzy commit gate denied the assertion."
                ),
                rule="LKB-FUZZY-COMMIT-001",
                task_id=target_task_id if isinstance(target_task_id, str) else None,
                repair_suggestions=tuple(
                    RepairSuggestion(
                        action="clarify_assumption",
                        target=a.assumption_id,
                        message=a.clarification_prompt,
                    )
                    for w in multi_world.worlds
                    for a in w.assumptions
                    if a.needs_clarification
                ),
            )
            derived_facts = tuple(
                f"Assumes({a.assertion_id}, {a.assumption_id}, {a.assumed_value})"
                for w in multi_world.worlds
                for a in w.assumptions
            )
            return self._denied(
                proposal,
                task_id=target_task_id if isinstance(target_task_id, str) else None,
                issues=(issue,),
                derived_facts=derived_facts,
                proof_trace=(
                    {
                        "rule": "LKB-FUZZY-COMMIT-001",
                        "premises": [a.assumption_id for w in multi_world.worlds for a in w.assumptions],
                        "conclusion": f"FuzzyCommitDecision({commit_decision.reason})",
                        "solverVersion": self.solver_version,
                    },
                ),
            )

        derived_facts = tuple(
            f"Assumes({a.assertion_id}, {a.assumption_id}, {a.assumed_value})"
            for w in multi_world.worlds
            for a in w.assumptions
        )
        # Register accepted assumptions in the TMS so later invalidation can
        # propagate to dependent task conclusions.
        self._register_assertion_in_tms(
            context,
            assertion_id=multi_world.assertion_id,
            worlds=multi_world.worlds,
            target_task_id=target_task_id if isinstance(target_task_id, str) else None,
        )
        return self._accepted(
            proposal,
            task_id=target_task_id if isinstance(target_task_id, str) else None,
            derived_facts=derived_facts,
            proof_trace=(
                {
                    "rule": "LKB-FUZZY-COMMIT-ALLOW",
                    "premises": [w.world_id for w in multi_world.worlds],
                    "conclusion": f"Aggregation({aggregation.strategy})",
                    "solverVersion": self.solver_version,
                },
            ),
        )

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
            return self._denied(
                proposal,
                issues=(issue,),
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
            return self._denied(
                proposal,
                issues=(issue,),
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
            return self._denied(
                proposal,
                issues=(issue,),
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

        # F-135: a task whose readiness depends on a stale derived fact must
        # not be allowed to commit a status transition.
        stale_check = self._check_stale_assumption_for_task(context, task_id)
        if stale_check is not None:
            return stale_check

        task = (getattr(context, "tasks", {}) or {}).get(task_id)
        if not isinstance(task, dict):
            issue = ValidationIssue(
                code="task_not_found",
                message=f"Task {task_id} does not exist.",
                rule="LKB-TRANSITION-001",
                task_id=task_id,
            )
            return self._denied(
                proposal,
                task_id=task_id,
                issues=(issue,),
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
                task_id=task_id,
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
                task_id=task_id,
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

        if target_status == "completed":
            engine_result = self.engine.evaluate(
                snapshot,
                target_task_id=task_id,
                target_status="completed",
                strict_acceptance=self._strict_acceptance_enabled(context, task, payload),
                acceptance_proof_present=self._has_acceptance_proof(task, payload),
            )
            if engine_result.result == "fail":
                issue = ValidationIssue(
                    code="completed_requires_acceptance_proof",
                    message=engine_result.message,
                    rule=engine_result.violated_rule or "R-005",
                    task_id=task_id,
                    repair_suggestions=(
                        RepairSuggestion(
                            action="add_acceptance_proof",
                            target=task_id,
                            message="Attach metadata.lkb.acceptance_proof before completing the task.",
                        ),
                    ),
                )
                return self._denied(
                    proposal,
                    task_id=task_id,
                    issues=(issue, *snapshot.warnings),
                    snapshot=snapshot,
                    derived_facts=engine_result.derived_facts,
                    proof_trace=engine_result.proof_trace,
                )
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=engine_result.derived_facts,
                proof_trace=engine_result.proof_trace,
            )

        if target_status == "in_progress":
            engine_result = self.engine.evaluate(
                snapshot,
                target_task_id=task_id,
                target_status="in_progress",
            )
            if engine_result.result == "fail":
                if engine_result.violated_rule == "R-006":
                    issue = ValidationIssue(
                        code="cyclic_dependency_blocks_readiness",
                        message=engine_result.message,
                        rule=engine_result.violated_rule,
                        task_id=task_id,
                        blockers=engine_result.cycle_tasks,
                        repair_suggestions=(
                            RepairSuggestion(
                                action="remove_dependency_cycle",
                                target=task_id,
                                message="Remove or rewrite one dependency edge in the cycle.",
                            ),
                        ),
                    )
                else:
                    blockers = list(active_blockers(snapshot, task_id))
                    issue = ValidationIssue(
                        code="blocked_task_cannot_enter_in_progress",
                        message=engine_result.message,
                        rule=engine_result.violated_rule or "R-002",
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
                return self._denied(
                    proposal,
                    task_id=task_id,
                    issues=(issue, *snapshot.warnings),
                    snapshot=snapshot,
                    derived_facts=engine_result.derived_facts,
                    proof_trace=engine_result.proof_trace,
                )
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=engine_result.derived_facts,
                proof_trace=engine_result.proof_trace,
            )

        return self._accepted(
            proposal,
            task_id=task_id,
            derived_facts=(f"CanMoveTo({task_id}, {target_status})",),
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
            return self._denied(
                proposal,
                task_id=task_id,
                issues=(issue,),
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
                task_id=task_id,
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
                task_id=task_id,
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
                return self._denied(
                    proposal,
                    task_id=task_id if isinstance(task_id, str) else None,
                    issues=(issue, *snapshot.warnings),
                    snapshot=snapshot,
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
                task_id=task_id,
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
            task_id=task_id,
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

    def _make_validation_run(
        self,
        proposal: Proposal,
        *,
        result: ValidationResult,
        task_id: str | None = None,
        derived_facts: tuple[str, ...] = (),
        proof_trace: tuple[dict[str, Any], ...] | None = None,
        issues: tuple[ValidationIssue, ...] = (),
        counterexample: dict[str, Any] | None = None,
        repair_suggestions: tuple[RepairSuggestion, ...] | None = None,
        input_facts_hash: str | None = None,
    ) -> ValidationRun:
        if repair_suggestions is None:
            suggestions: list[RepairSuggestion] = []
            for issue in issues:
                suggestions.extend(issue.repair_suggestions)
            repair_suggestions = tuple(suggestions)
        return ValidationRun(
            validation_run_id=_new_id("V-"),
            proposal_id=proposal.proposal_id,
            task_id=task_id,
            input_facts_hash=input_facts_hash or proposal.snapshot_hash,
            ruleset_hash=_RULESET_HASH,
            snapshot_hash=proposal.snapshot_hash,
            engine="layer1-python",
            engine_version=self.solver_version,
            result=result,
            derived_facts=derived_facts,
            proof_trace=proof_trace
            or (
                {
                    "rule": "LKB-FOUNDATION-ALLOW",
                    "conclusion": "No foundation rule denied this change.",
                    "solverVersion": self.solver_version,
                },
            ),
            counterexample=counterexample,
            repair_suggestions=repair_suggestions,
            issues=issues,
            created_at=datetime.now(timezone.utc).isoformat(),
            requested_by=proposal.change.actor or "system",
        )

    def _counterexample_for(
        self,
        issue: ValidationIssue,
        snapshot: FactsSnapshot,
        task_id: str | None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "violatedRule": issue.rule,
            "violatedPredicate": issue.code,
        }
        if task_id:
            out["taskId"] = task_id
        if issue.blockers:
            out["activeBlockers"] = list(issue.blockers)
        if task_id and task_id in snapshot.normalized_tasks:
            task = snapshot.normalized_tasks[task_id]
            out["model"] = {
                f"Status({task_id})": task["status"],
            }
            if issue.blockers:
                out["model"].update(
                    {
                        f"Status({blocker})": snapshot.normalized_tasks.get(blocker, {}).get(
                            "status"
                        )
                        for blocker in issue.blockers
                        if blocker in snapshot.normalized_tasks
                    }
                )
        return out

    def _denied(
        self,
        proposal: Proposal,
        *,
        task_id: str | None = None,
        issues: tuple[ValidationIssue, ...] = (),
        snapshot: FactsSnapshot | None = None,
        derived_facts: tuple[str, ...] = (),
        proof_trace: tuple[dict[str, Any], ...] | None = None,
        counterexample: dict[str, Any] | None = None,
        repair_suggestions: tuple[RepairSuggestion, ...] | None = None,
        result: ValidationResult = "fail",
    ) -> ValidationRun:
        if counterexample is None and issues:
            counterexample = self._counterexample_for(
                issues[0],
                snapshot or build_facts_snapshot(SimpleNamespace(tasks={}, todos=())),  # type: ignore[arg-type]
                task_id,
            )
        return self._make_validation_run(
            proposal,
            result=result,
            task_id=task_id,
            derived_facts=derived_facts,
            proof_trace=proof_trace,
            issues=issues,
            counterexample=counterexample,
            repair_suggestions=repair_suggestions,
        )

    def _accepted(
        self,
        proposal: Proposal,
        *,
        task_id: str | None = None,
        proof_trace: tuple[dict[str, Any], ...] | None = None,
        derived_facts: tuple[str, ...] = (),
    ) -> ValidationRun:
        return self._make_validation_run(
            proposal,
            result="pass",
            task_id=task_id,
            derived_facts=derived_facts,
            proof_trace=proof_trace,
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

    def _tms(self, context: "ToolContext") -> TruthMaintenanceSystem:
        return get_logical_kanban(context).tms

    def _check_stale_assumption_for_task(
        self,
        context: "ToolContext",
        task_id: str,
    ) -> ValidationRun | None:
        """Return a stale ValidationRun if task_id depends on a stale assertion."""
        tms = self._tms(context)
        if not tms.is_task_affected(task_id):
            return None
        stale_assertions = [
            assertion.assertion_id
            for assertion in tms.get_assertions_for_task(task_id)
            if assertion.status == "stale"
        ]
        issue = ValidationIssue(
            code="stale_assumption_blocks_transition",
            message=(
                f"Task {task_id} cannot change status because one or more "
                "assumptions it depends on have been invalidated."
            ),
            rule="LKB-TMS-001",
            task_id=task_id,
            repair_suggestions=(
                RepairSuggestion(
                    action="clarify_assumption",
                    target=task_id,
                    message="Clarify or override the invalidated assumptions before transitioning.",
                ),
            ),
        )
        # Build a minimal proposal-like object for _denied.
        proposal = Proposal(
            proposal_id="TMS-STALE",
            change=ProposedChange(
                kind="transition_status",
                payload={"taskId": task_id},
            ),
            snapshot_hash="",
        )
        return self._denied(
            proposal,
            task_id=task_id,
            issues=(issue,),
            result="stale",
            derived_facts=tuple(f"Stale({aid})" for aid in stale_assertions),
            proof_trace=(
                {
                    "rule": "LKB-TMS-001",
                    "premises": [f"Task({task_id})"] + [f"Stale({aid})" for aid in stale_assertions],
                    "conclusion": f"Not(CanMoveTo({task_id}, _))",
                    "solverVersion": self.solver_version,
                },
            ),
        )

    def _register_assertion_in_tms(
        self,
        context: "ToolContext",
        *,
        assertion_id: str,
        worlds: tuple["World", ...],
        target_task_id: str | None,
    ) -> None:
        """Register all assumptions from accepted worlds in the TMS."""
        tms = self._tms(context)
        task_ids = (target_task_id,) if target_task_id else ()
        # Each world carries the same set of ambiguities; register assumptions
        # from the first world as the canonical dependency set.
        assumptions = worlds[0].assumptions if worlds else ()
        tms.register_assertion(
            assertion_id,
            assumptions=assumptions,
            derived_from=(),
            task_ids=task_ids,
        )

    def clarify_assumption(
        self,
        context: "ToolContext",
        assumption_id: str,
        clarification: "Clarification",
    ) -> tuple["AssumptionRecord", "AssumptionRecord" | None, ValidationRun | None]:
        """Apply a user clarification and revalidate affected tasks.

        Returns the new/old assumption records and, if a single task was
        affected and the clarification resolves all stale dependencies, a
        fresh validation run for that task's current transition intent.
        """
        from .fuzzy_types import Clarification

        if not isinstance(clarification, Clarification):
            raise TypeError("clarification must be a Clarification instance")
        tms = self._tms(context)
        new_record, old_record = tms.clarify_assumption(assumption_id, clarification)
        validation_run: ValidationRun | None = None

        affected = tms.get_stale_task_ids()
        if len(affected) == 0:
            # No remaining stale tasks; revalidate any previously affected task
            # that is now ready again.  We use the task linked to the clarified
            # assumption's assertion if exactly one exists.
            assertion = tms.get_assertion(new_record.assertion_id)
            task_ids = assertion.task_ids if assertion else set()
            if len(task_ids) == 1:
                task_id = next(iter(task_ids))
                task = (getattr(context, "tasks", {}) or {}).get(task_id)
                if isinstance(task, dict) and task.get("status") == "pending":
                    change = ProposedChange(
                        kind="transition_status",
                        payload={"taskId": task_id, "status": "in_progress"},
                    )
                    validation_run = self.run(change, context)[1]
        return new_record, old_record, validation_run
