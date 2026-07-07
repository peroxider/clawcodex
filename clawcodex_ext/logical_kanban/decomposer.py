"""Task decomposition service for Logical Kanban (F-149).

The decomposer is a proposal generator: it turns a high-level natural-language
goal into a structured, logic-aware task plan, but it never mutates task state.
Every generated plan is run through the LKB validation gate (ambiguity detection
+ dependency-graph validation) before it is returned to the agent.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .ambiguity_detector import AmbiguityDetector
from .audit import (
    AuditLog,
    InMemoryAuditLog,
    event_for_decomposition_proposed,
    event_for_method_referenced,
)
from .context_adapter import build_facts_snapshot
from .fuzzy_types import AmbiguityReport
from .method_prompt import summarize_methods
from .rule_engine import Layer1RuleEngine
from .solver_adapter import SolverRequest
from .solver_pipeline import SolverPipeline
from .types import FactsSnapshot, ValidationIssue, ValidationRun

if TYPE_CHECKING:
    from .method_library import EngineeringMethod
    from clawcodex_ext.providers.base import BaseProvider
    from clawcodex_ext.tool_system.context import ToolContext


@dataclass(frozen=True)
class ProposedTask:
    """One concrete task proposed by the decomposer."""

    proposed_task_id: str
    subject: str
    description: str
    active_form: str
    acceptance_criteria: tuple[str, ...]
    blocked_by: tuple[str, ...]
    lkb_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposedTaskId": self.proposed_task_id,
            "subject": self.subject,
            "description": self.description,
            "activeForm": self.active_form,
            "acceptanceCriteria": list(self.acceptance_criteria),
            "blockedBy": list(self.blocked_by),
            "lkbMetadata": dict(self.lkb_metadata),
        }


@dataclass(frozen=True)
class DecompositionPlan:
    """Validated plan produced by :class:`TaskDecomposer`."""

    decomposition_run_id: str
    goal: str
    tasks: tuple[ProposedTask, ...]
    dependencies: tuple[tuple[str, str], ...]
    assumptions: tuple[str, ...]
    ambiguity_report: AmbiguityReport | None
    validation_run: ValidationRun | None
    # F-151: de-duplicated list of method_ref strings the LLM used across
    # the plan.  Empty when the LLM decomposed freely without anchoring to
    # a method.  Order follows first-occurrence in ``self.tasks``.
    method_references: tuple[str, ...] = ()
    # F-152: optional scheduling metadata captured at the call site.
    # When non-None, the decomposer hands the plan to
    # :class:`~clawcodex_ext.logical_kanban.scheduling_solver.SchedulingSolver`
    # and stores the resulting :class:`~clawcodex_ext.logical_kanban.
    # scheduling_solver.Schedule` in :attr:`schedule`.  When the
    # ``[scheduling]`` extra is not installed, ``scheduling_constraints``
    # is preserved verbatim but ``schedule`` stays ``None`` so callers
    # can still introspect the request.
    scheduling_constraints: dict[str, Any] | None = None
    schedule: Any = None  # Schedule | None — typed loosely to avoid an
    # import cycle (scheduling_solver imports nothing from this module).

    @property
    def validation_run_id(self) -> str | None:
        return self.validation_run.validation_run_id if self.validation_run else None

    def to_dict(self) -> dict[str, Any]:
        from .fuzzy_types import AmbiguityReport

        ambiguity: dict[str, Any] | None = None
        if self.ambiguity_report is not None:
            if isinstance(self.ambiguity_report, AmbiguityReport):
                ambiguity = self.ambiguity_report.to_dict()
            else:
                ambiguity = dict(self.ambiguity_report)
        return {
            "decompositionRunId": self.decomposition_run_id,
            "goal": self.goal,
            "tasks": [t.to_dict() for t in self.tasks],
            "dependencies": [list(d) for d in self.dependencies],
            "assumptions": list(self.assumptions),
            "ambiguities": ambiguity.get("detectedAmbiguities", []) if ambiguity else [],
            "methodReferences": list(self.method_references),
            "schedulingConstraints": (
                self._serialize_scheduling_constraints()
                if self.scheduling_constraints is not None
                else None
            ),
            "schedule": self.schedule.to_dict() if self.schedule is not None else None,
        }

    def _serialize_scheduling_constraints(self) -> dict[str, Any]:
        """Deep-serialize scheduling_constraints for JSON output.

        Converts ``Resource`` objects inside ``resources`` to their
        JSON-compatible dict form (via :meth:`Resource.to_dict`).
        """
        from .scheduling_solver import Resource as _Resource

        assert self.scheduling_constraints is not None
        sc = dict(self.scheduling_constraints)
        raw_resources = sc.get("resources")
        if isinstance(raw_resources, (list, tuple)):
            sc["resources"] = [
                r.to_dict() if isinstance(r, _Resource) else r
                for r in raw_resources
            ]
        return sc


# JSON schema shape the LLM must return.
_TASK_KEYS = {
    "proposedTaskId",
    "subject",
    "description",
    "activeForm",
    "acceptanceCriteria",
    "blockedBy",
    "lkbMetadata",
}
# F-150 added ``method_ref`` so the LLM can attach a method-library reference
# to a ProposedTask.  The field is OPTIONAL: omitting it leaves the task
# un-method-tagged.  When present it must be a non-empty string (see
# ``_validate_lkb_metadata`` below).
#
# F-152 added ``scheduling_required`` (boolean) so an LLM can flag a
# task as needing a scheduling pass.  The actual scheduling metadata
# (``resources`` / ``deadline`` / ``objective``) lives at the plan
# level (``DecompositionPlan.scheduling_constraints``), not on each
# task; this per-task flag exists so the LLM can ask for a schedule
# without supplying the constraints itself.  ``duration`` and
# ``earliest_start`` are accepted so the LLM can supply per-task
# scheduling hints that the LKB scheduling pass picks up.
_LKB_METADATA_KEYS = {
    "assertions",
    "acceptance_proof",
    "assumptions",
    "strict_acceptance",
    "method_ref",
    "scheduling_required",
    "duration",
    "earliest_start",
}


class TaskDecomposer:
    """Generate and validate a task decomposition plan for a high-level goal."""

    def __init__(
        self,
        llm_provider: "BaseProvider | None" = None,
        *,
        ambiguity_detector: AmbiguityDetector | None = None,
        solver_pipeline: SolverPipeline | None = None,
        max_retries: int = 1,
        method_library: tuple["EngineeringMethod", ...] | None = None,
    ) -> None:
        # F-150: optionally pin the method library used for R-METHOD-* checks.
        # ``None`` means "use the default METHOD_LIBRARY at validation time".
        # We resolve to a concrete tuple so the snapshot of the library at
        # constructor time is used for all subsequent ``decompose()`` calls.
        if method_library is None:
            from .method_library import METHOD_LIBRARY

            method_library = METHOD_LIBRARY
        self.method_library = method_library
        self.llm_provider = llm_provider
        self.ambiguity_detector = ambiguity_detector or AmbiguityDetector()
        self.solver_pipeline = solver_pipeline or SolverPipeline()
        self.max_retries = max(0, max_retries)

    def decompose(
        self,
        goal: str,
        *,
        context: str = "",
        acceptance_criteria: tuple[str, ...] = (),
        max_steps: int = 8,
        existing_tasks: tuple[dict[str, Any], ...] = (),
        scheduling_constraints: dict[str, Any] | None = None,
    ) -> DecompositionPlan:
        """Return a validated decomposition plan for ``goal``.

        Parameters
        ----------
        goal:
            High-level natural-language goal.
        context:
            Optional surrounding context (codebase state, constraints, ...).
        acceptance_criteria:
            Optional top-level acceptance criteria for the whole goal.
        max_steps:
            Maximum number of proposed tasks.
        existing_tasks:
            Existing tasks that the plan must coexist with. Each entry should
            use the same shape as ``ToolContext.tasks`` values.
        scheduling_constraints:
            F-152: optional scheduling parameters.  When non-None, the
            decomposer hands the plan to
            :class:`~clawcodex_ext.logical_kanban.scheduling_solver.
            SchedulingSolver` after the LLM pass completes and stores
            the result in :attr:`DecompositionPlan.schedule`.  The
            accepted shape is::

                {
                    "resources": [Resource, ...],   # required
                    "horizon": int,                 # required
                    "objective": str,               # optional, default "makespan"
                    "timeout_seconds": float,       # optional
                }

            If OR-Tools is not installed the constraints are still
            persisted on the plan, but ``schedule`` stays ``None``.
        """
        if self.llm_provider is None:
            raise ValueError("TaskDecomposer requires an LLM provider")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if scheduling_constraints is not None and not isinstance(
            scheduling_constraints, dict
        ):
            raise ValueError("scheduling_constraints must be a dict or None")

        decomposition_run_id = _new_id("D-")
        raw_plan = self._generate_raw_plan(
            goal=goal,
            context=context,
            acceptance_criteria=acceptance_criteria,
            max_steps=max_steps,
            existing_tasks=existing_tasks,
            decomposition_run_id=decomposition_run_id,
        )
        tasks, dependencies, assumptions = _parse_raw_plan(raw_plan, max_steps)

        # Ambiguity detection over the generated plan.
        ambiguity_report = self._detect_ambiguities(tasks, decomposition_run_id)

        # Dependency-graph validation via LKB snapshot + solver pipeline.
        validation_run = self._validate_plan(
            tasks=tasks,
            dependencies=dependencies,
            existing_tasks=existing_tasks,
            decomposition_run_id=decomposition_run_id,
            ambiguity_report=ambiguity_report,
        )

        # F-152: optional scheduling pass.  We compute the schedule
        # *before* constructing the plan so it can be stored on the
        # final immutable value.  Failures are degraded to ``None`` so a
        # bad schedule never blocks the LLM-generated plan.
        schedule = None
        if scheduling_constraints is not None:
            schedule = self._run_scheduling_pass(
                tasks=tasks,
                dependencies=dependencies,
                scheduling_constraints=scheduling_constraints,
            )

        plan = DecompositionPlan(
            decomposition_run_id=decomposition_run_id,
            goal=goal,
            tasks=tasks,
            dependencies=dependencies,
            assumptions=assumptions,
            ambiguity_report=ambiguity_report,
            validation_run=validation_run,
            method_references=_collect_method_references(
                tasks, self.method_library
            ),
            scheduling_constraints=scheduling_constraints,
            schedule=schedule,
        )

        # Audit trail — one event per decomposition run.
        self._emit_audit_event(plan)

        return plan

    @staticmethod
    def _run_scheduling_pass(
        *,
        tasks: tuple[ProposedTask, ...],
        dependencies: tuple[tuple[str, str], ...],
        scheduling_constraints: dict[str, Any],
    ) -> Any:
        """Best-effort SchedulingSolver invocation.  Returns the
        :class:`Schedule` on success, or ``None`` on any failure.

        The mapping from :class:`ProposedTask` (LLM-shaped) to
        :class:`SchedulingTask` (CP-SAT-shaped) is lossy — we pick
        conservative defaults for duration and time windows because the
        LLM does not usually surface numeric bounds.  Callers that need
        tighter modelling should construct :class:`SchedulingTask` and
        :class:`Resource` instances directly and call
        :class:`SchedulingSolver` themselves.
        """
        from .scheduling_solver import (
            Resource,
            SchedulingError,
            SchedulingSolver,
            SchedulingTask,
            SchedulingUnavailable,
            validate_schedule,
        )

        resources = scheduling_constraints.get("resources")
        horizon = scheduling_constraints.get("horizon")
        # F-152 设计文档用 ``deadline`` 作为 horizon 的别名。
        if horizon is None:
            horizon = scheduling_constraints.get("deadline")
        objective = scheduling_constraints.get("objective", "makespan")
        timeout_seconds = float(scheduling_constraints.get("timeout_seconds", 5.0))

        if not isinstance(resources, (list, tuple)) or not resources:
            return None

        # Accept both Resource objects and raw dicts — the latter is the
        # common path when the LLM passes scheduling_constraints through
        # the TaskDecompose tool (which serialises via JSON).
        parsed_resources: list[Resource] = []
        for r in resources:
            if isinstance(r, Resource):
                parsed_resources.append(r)
            elif isinstance(r, dict):
                try:
                    parsed_resources.append(Resource.from_dict(r))
                except (SchedulingError, TypeError, ValueError):
                    return None
            else:
                return None

        if not all(isinstance(r, Resource) for r in parsed_resources):
            return None
        if not isinstance(horizon, int) or horizon < 1:
            return None

        # Build a ``predecessor -> set(dependent)`` map so each task
        # carries the dependencies that target it.
        predecessors: dict[str, list[str]] = {t.proposed_task_id: [] for t in tasks}
        for prereq, dependent in dependencies:
            if dependent in predecessors and prereq in predecessors:
                predecessors[dependent].append(prereq)

        scheduling_tasks: list[SchedulingTask] = []
        for t in tasks:
            # Per-task scheduling hints may live in ``lkb_metadata`` —
            # a future F-N could add ``duration``, ``earliest_start``,
            # ``required_skills``.  For F-152 we only honour an
            # optional ``duration`` integer override so the user can
            # shape individual task lengths without rewriting the LLM
            # prompt.
            duration = t.lkb_metadata.get("duration", 1)
            if not isinstance(duration, int) or duration < 1:
                duration = 1
            earliest_start = t.lkb_metadata.get("earliest_start")
            if earliest_start is not None and (
                not isinstance(earliest_start, int) or earliest_start < 0
            ):
                earliest_start = None
            scheduling_tasks.append(
                SchedulingTask(
                    task_id=t.proposed_task_id,
                    duration=duration,
                    earliest_start=earliest_start,
                    predecessors=tuple(predecessors[t.proposed_task_id]),
                )
            )

        try:
            solver = SchedulingSolver()
        except SchedulingUnavailable:
            return None

        try:
            schedule = solver.schedule(
                scheduling_tasks,
                parsed_resources,
                horizon=horizon,
                objective=objective,
                timeout_seconds=timeout_seconds,
            )
        except Exception:  # noqa: BLE001
            return None

        # Defensive validation — the solver should already satisfy all
        # constraints, but we re-verify so LKB can flag corrupt data.
        issues = validate_schedule(
            schedule,
            scheduling_tasks,
            parsed_resources,
            dependencies=dependencies,
        )
        if issues:
            return None
        return schedule

    def _generate_raw_plan(
        self,
        *,
        goal: str,
        context: str,
        acceptance_criteria: tuple[str, ...],
        max_steps: int,
        existing_tasks: tuple[dict[str, Any], ...],
        decomposition_run_id: str,
    ) -> dict[str, Any]:
        prompt = self._build_prompt(
            goal=goal,
            context=context,
            acceptance_criteria=acceptance_criteria,
            max_steps=max_steps,
            existing_tasks=existing_tasks,
        )
        system_prompt = self._system_prompt(max_steps, goal=goal)

        last_error: Exception | None = None
        raw = ""
        for attempt in range(self.max_retries + 1):
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            if attempt:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous response was invalid. Return only strict "
                            "JSON matching the requested DecompositionPlan shape."
                        ),
                    }
                )
            try:
                response = self.llm_provider.chat(messages, temperature=0)
                raw = getattr(response, "content", "") or ""
                return _extract_and_validate_plan(raw, max_steps)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise TaskDecompositionError(
            f"Could not generate a valid decomposition plan: {last_error}"
        ) from last_error

    @staticmethod
    def _system_prompt(max_steps: int, *, goal: str = "") -> str:
        # F-151: when a method library is available, render a compact
        # summary block inside the system prompt so the LLM can prefer
        # the existing decomposition templates over free-form invention.
        # The summary is bounded to ``max_tokens`` (default 1 800) so it
        # never dominates the context window — see ``method_prompt.summarize_methods``.
        from .method_library import METHOD_LIBRARY as _DEFAULT_LIBRARY
        from .method_prompt import select_methods_by_pattern

        try:
            relevant = select_methods_by_pattern(goal, _DEFAULT_LIBRARY, top_k=10)
        except Exception:  # pragma: no cover - defensive guard
            relevant = ()

        method_block = ""
        if relevant:
            summary = summarize_methods(
                relevant,
                goal=goal,
                max_tokens=1800,
                header="## Engineering Methods (use these templates when applicable)",
            )
            method_block = (
                "\n\n"
                f"{summary.text}\n"
                "If a method above matches the user's goal, STRONGLY PREFER its "
                "decomposition shape.  Carry its ``method_id`` in each "
                "affected task's ``lkbMetadata.method_ref`` field."
            )

        return (
            "You are a task-decomposition assistant for a logical kanban system. "
            "Return strictly JSON (no markdown). "
            "Break the user's goal into concrete, actionable tasks. "
            "Each task subject must be in imperative form (e.g. 'Implement X'). "
            "Each task must have at least one acceptance criterion. "
            "Dependencies must be acyclic and only reference IDs listed in tasks or existingTasks. "
            f"Emit at most {max_steps} tasks. "
            "Shape: {\"tasks\": [{\"proposedTaskId\": \"tmp-...\", "
            "\"subject\": \"...\", \"description\": \"...\", "
            "\"activeForm\": \"...\", \"acceptanceCriteria\": [\"...\"], "
            "\"blockedBy\": [\"tmp-...\"], "
            "\"lkbMetadata\": {\"assertions\": [...], \"acceptance_proof\": \"...\", "
            "\"assumptions\": [...], \"strict_acceptance\": false, "
            "\"method_ref\": \"M-add-api-endpoint-001\"}}], "
            "\"dependencies\": [[\"tmp-a\", \"tmp-b\"]], "
            "\"assumptions\": [\"...\"]}. "
            "accepted lkbMetadata keys: assertions, acceptance_proof, "
            "assumptions, strict_acceptance, method_ref.  method_ref is "
            "optional; when present it MUST be a method_id from the "
            "engineering method library."
            f"{method_block}"
        )

    @staticmethod
    def _build_prompt(
        *,
        goal: str,
        context: str,
        acceptance_criteria: tuple[str, ...],
        max_steps: int,
        existing_tasks: tuple[dict[str, Any], ...],
    ) -> str:
        parts: list[str] = [f"Goal:\n{goal}"]
        if context:
            parts.append(f"Context:\n{context}")
        if acceptance_criteria:
            parts.append("Top-level acceptance criteria:\n- " + "\n- ".join(acceptance_criteria))
        if existing_tasks:
            lines = []
            for task in existing_tasks:
                task_id = task.get("id") or task.get("taskId") or "?"
                subject = task.get("subject") or task.get("content") or ""
                status = task.get("status") or "pending"
                lines.append(f"- {task_id} [{status}]: {subject}")
            parts.append("Existing tasks:\n" + "\n".join(lines))
        parts.append(f"Limit the plan to at most {max_steps} tasks.")
        return "\n\n".join(parts)

    def _detect_ambiguities(
        self,
        tasks: tuple[ProposedTask, ...],
        decomposition_run_id: str,
    ) -> AmbiguityReport | None:
        from .fuzzy_types import Ambiguity, Severity

        all_ambiguities: list[Ambiguity] = []
        for task in tasks:
            texts = [
                task.subject,
                task.description,
                " ".join(task.acceptance_criteria),
            ]
            for text in texts:
                if not text:
                    continue
                report = self.ambiguity_detector.detect(
                    text,
                    assertion_id=f"{decomposition_run_id}:{task.proposed_task_id}",
                )
                all_ambiguities.extend(report.detected_ambiguities)

        severity: Severity = "negligible"
        if all_ambiguities:
            order = ("negligible", "minor", "major", "critical")
            severity = max(
                (a.severity for a in all_ambiguities),
                key=lambda s: order.index(s),
            )
        needs_clarification = any(
            a.severity in ("critical", "major")
            or a.kind
            in (
                "semantic_vagueness",
                "unclear_dependency_direction",
                "missing_subject",
                "missing_object",
            )
            for a in all_ambiguities
        )
        return AmbiguityReport(
            assertion_id=decomposition_run_id,
            detected_ambiguities=tuple(all_ambiguities),
            severity=severity,
            needs_clarification=needs_clarification,
        )

    def _validate_plan(
        self,
        *,
        tasks: tuple[ProposedTask, ...],
        dependencies: tuple[tuple[str, str], ...],
        existing_tasks: tuple[dict[str, Any], ...],
        decomposition_run_id: str,
        ambiguity_report: AmbiguityReport | None,
    ) -> ValidationRun:
        # Build a temporary ToolContext containing existing + proposed tasks.
        temp_context = self._build_validation_context(tasks, existing_tasks)
        snapshot = build_facts_snapshot(temp_context)

        issues: list[ValidationIssue] = []

        # Surface cycles detected by the LKB snapshot builder.
        if snapshot.cycle_task_ids:
            cycle_ids = sorted(snapshot.cycle_task_ids)
            issues.append(
                ValidationIssue(
                    code="decomposition_cyclic_dependency",
                    message=(
                        "Proposed dependency graph contains a cycle involving: "
                        f"{', '.join(cycle_ids)}."
                    ),
                    rule="LKB-R-006",
                    task_id=cycle_ids[0] if cycle_ids else None,
                    blockers=tuple(cycle_ids),
                    repair_suggestions=(),
                )
            )

        # Surface dangling / impossible dependencies.
        for task_id, task in snapshot.normalized_tasks.items():
            if not task_id.startswith("tmp-"):
                continue
            for warning in snapshot.warnings:
                if warning.task_id == task_id and warning.code == "dangling_blocker":
                    issues.append(
                        ValidationIssue(
                            code="decomposition_dangling_dependency",
                            message=warning.message,
                            rule=warning.rule,
                            task_id=task_id,
                            blockers=warning.blockers,
                        )
                    )

        # Surface ambiguous acceptance criteria or descriptions.
        if ambiguity_report is not None and ambiguity_report.needs_clarification:
            for ambiguity in ambiguity_report.detected_ambiguities:
                issues.append(
                    ValidationIssue(
                        code="decomposition_ambiguous_criterion",
                        message=(
                            f"Ambiguous phrase '{ambiguity.phrase}' "
                            f"({ambiguity.kind}, severity={ambiguity.severity})."
                        ),
                        rule="LKB-FUZZY-001",
                        repair_suggestions=(),
                    )
                )

        # F-150: emit method-compliance warnings (R-METHOD-001/002/003).
        # These never block the commit per the F-150 design decision; the
        # ``_merge_result`` helper only flips the result to ``fail`` for
        # error-severity issues, so warnings ride along in the ValidationRun.
        from .rule_engine import validate_method_compliance

        method_plan = DecompositionPlan(
            decomposition_run_id=decomposition_run_id,
            goal="",
            tasks=tasks,
            dependencies=dependencies,
            assumptions=(),
            ambiguity_report=ambiguity_report,
            validation_run=None,
        )
        issues.extend(
            validate_method_compliance(method_plan, method_library=self.method_library)
        )

        # Run the solver pipeline on the snapshot for a canonical ValidationRun.
        request = SolverRequest(snapshot=snapshot)
        pipeline_result = self.solver_pipeline.validate(
            request,
            proposal_id=decomposition_run_id,
            timeout_seconds=10.0,
            requested_by="TaskDecomposer",
        )

        overall_result = self._merge_result(pipeline_result.result, issues)

        return ValidationRun(
            validation_run_id=pipeline_result.validation_run_id,
            proposal_id=decomposition_run_id,
            task_id=None,
            input_facts_hash=snapshot.hash,
            ruleset_hash="",
            snapshot_hash=snapshot.hash,
            engine=pipeline_result.engine,
            engine_version=pipeline_result.engine_version,
            result=overall_result,
            duration_ms=pipeline_result.duration_ms,
            derived_facts=pipeline_result.derived_facts,
            proof_trace=pipeline_result.proof_trace,
            counterexample=pipeline_result.counterexample,
            repair_suggestions=pipeline_result.repair_suggestions,
            issues=tuple(issues),
            created_at=pipeline_result.created_at,
            requested_by="TaskDecomposer",
            solver_results=pipeline_result.solver_results,
        )

    @staticmethod
    def _build_validation_context(
        tasks: tuple[ProposedTask, ...],
        existing_tasks: tuple[dict[str, Any], ...],
    ) -> "ToolContext":
        from clawcodex_ext.tool_system.context import ToolContext
        from pathlib import Path

        ctx = ToolContext(workspace_root=Path("."), session_id="decomposer-validation")
        # Existing tasks keep their real status.
        for task in existing_tasks:
            task_id = task.get("id") or task.get("taskId")
            if not isinstance(task_id, str) or not task_id:
                continue
            ctx.tasks[task_id] = dict(task)

        # Proposed tasks enter as pending with dependency metadata.
        for task in tasks:
            ctx.tasks[task.proposed_task_id] = {
                "id": task.proposed_task_id,
                "subject": task.subject,
                "description": task.description,
                "activeForm": task.active_form,
                "status": "pending",
                "owner": None,
                "blocks": [],
                "blockedBy": list(task.blocked_by),
                "metadata": {"lkb": dict(task.lkb_metadata)},
                "output": "",
            }

        # Mirror blockedBy in blocks so the snapshot graph is consistent.
        for task in tasks:
            for blocker_id in task.blocked_by:
                blocker = ctx.tasks.get(blocker_id)
                if blocker is None:
                    continue
                blocks = list(blocker.get("blocks") or [])
                if task.proposed_task_id not in blocks:
                    blocks.append(task.proposed_task_id)
                blocker["blocks"] = blocks

        return ctx

    @staticmethod
    def _merge_result(
        pipeline_result: str,
        issues: list[ValidationIssue],
    ) -> "Any":
        from .types import ValidationResult

        # F-150: warnings (e.g. R-METHOD-*) must NOT block the commit per
        # the F-150 design decision ("MVP 阶段保证向后兼容").  Only
        # severity='error' issues flip the result to 'fail'.
        if any(issue.severity == "error" for issue in issues):
            return "fail"
        if pipeline_result in ("pass", "fail", "unknown", "timeout", "error", "stale"):
            return pipeline_result  # type: ignore[return-value]
        return "unknown" if pipeline_result != "pass" else "pass"

    def _emit_audit_event(
        self,
        plan: DecompositionPlan,
        *,
        audit_log: "InMemoryAuditLog | AuditLog | None" = None,
    ) -> None:
        # We don't have a ToolContext here, so we emit to an in-memory audit log
        # by default. Callers that own a context can pass an explicit
        # ``audit_log`` (e.g. ``get_audit_log(context)``) for session-local
        # persistence. Tests pass their own log to inspect emitted events.
        validation_run = plan.validation_run
        log = audit_log if audit_log is not None else InMemoryAuditLog()

        event = event_for_decomposition_proposed(
            decomposition_run_id=plan.decomposition_run_id,
            goal=plan.goal,
            task_count=len(plan.tasks),
            dependency_count=len(plan.dependencies),
            ambiguity_count=(
                len(plan.ambiguity_report.detected_ambiguities)
                if plan.ambiguity_report is not None
                else 0
            ),
            validation_run_id=plan.validation_run_id,
            result=validation_run.result if validation_run else "unknown",
        )
        log.append(event)

        # F-151: emit one ``lkb_method_referenced`` event per unique
        # method_ref surfaced in the plan.  ``plan.method_references`` is
        # already de-duplicated (first-occurrence order), so each referenced
        # method produces exactly one event per emission call.
        if plan.method_references:
            method_task_counts = _count_method_task_usage(plan.tasks)
            for method_id in plan.method_references:
                method_event = event_for_method_referenced(
                    decomposition_run_id=plan.decomposition_run_id,
                    method_id=method_id,
                    task_count=method_task_counts.get(method_id, 0),
                    validation_run_id=plan.validation_run_id,
                )
                log.append(method_event)


class TaskDecompositionError(Exception):
    """Raised when the decomposer cannot produce a valid plan."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _extract_and_validate_plan(raw: str, max_steps: int) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TaskDecompositionError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskDecompositionError("LLM response must be a JSON object")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise TaskDecompositionError("'tasks' must be a list")
    if len(tasks) > max_steps:
        raise TaskDecompositionError(f"LLM returned {len(tasks)} tasks; max is {max_steps}")
    if not tasks:
        raise TaskDecompositionError("'tasks' must not be empty")

    seen_ids: set[str] = set()
    parsed_tasks: list[ProposedTask] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise TaskDecompositionError(f"tasks[{index}] must be an object")
        _reject_unknown_keys(task, _TASK_KEYS, f"tasks[{index}]")
        task_id = task.get("proposedTaskId")
        if not isinstance(task_id, str) or not task_id:
            raise TaskDecompositionError(f"tasks[{index}].proposedTaskId must be a non-empty string")
        if task_id in seen_ids:
            raise TaskDecompositionError(f"duplicate proposedTaskId: {task_id}")
        seen_ids.add(task_id)

        subject = _require_string(task, "subject", f"tasks[{index}]")
        description = _require_string(task, "description", f"tasks[{index}]")
        active_form = task.get("activeForm", "")
        if not isinstance(active_form, str):
            raise TaskDecompositionError(f"tasks[{index}].activeForm must be a string")

        acceptance_criteria = _string_list(task.get("acceptanceCriteria"))
        if not acceptance_criteria:
            raise TaskDecompositionError(
                f"tasks[{index}] must have at least one acceptance criterion"
            )

        blocked_by = _string_list(task.get("blockedBy"))
        if task_id in blocked_by:
            raise TaskDecompositionError(f"tasks[{index}] cannot block itself")

        lkb_metadata = dict(task.get("lkbMetadata") or {})
        _validate_lkb_metadata(lkb_metadata, f"tasks[{index}].lkbMetadata")

        parsed_tasks.append(
            ProposedTask(
                proposed_task_id=task_id,
                subject=subject,
                description=description,
                active_form=active_form,
                acceptance_criteria=tuple(acceptance_criteria),
                blocked_by=tuple(blocked_by),
                lkb_metadata=lkb_metadata,
            )
        )

    dependencies = data.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise TaskDecompositionError("'dependencies' must be a list")
    parsed_dependencies: list[tuple[str, str]] = []
    for dep_index, dep in enumerate(dependencies):
        if not isinstance(dep, (list, tuple)) or len(dep) != 2:
            raise TaskDecompositionError(f"dependencies[{dep_index}] must be a pair")
        prereq, dependent = dep
        if not isinstance(prereq, str) or not isinstance(dependent, str):
            raise TaskDecompositionError(
                f"dependencies[{dep_index}] entries must be strings"
            )
        if prereq not in seen_ids:
            raise TaskDecompositionError(
                f"dependencies[{dep_index}] references unknown task {prereq!r}"
            )
        if dependent not in seen_ids:
            raise TaskDecompositionError(
                f"dependencies[{dep_index}] references unknown task {dependent!r}"
            )
        parsed_dependencies.append((prereq, dependent))

    # Ensure blockedBy and dependencies agree: every blockedBy must have a
    # matching dependency edge.
    blocked_by_edges: set[tuple[str, str]] = set()
    for task in parsed_tasks:
        for blocker in task.blocked_by:
            blocked_by_edges.add((blocker, task.proposed_task_id))
    dependency_edges = set(parsed_dependencies)
    for edge in blocked_by_edges:
        if edge not in dependency_edges:
            parsed_dependencies.append(edge)

    assumptions = _string_list(data.get("assumptions"))

    return {
        "tasks": tuple(parsed_tasks),
        "dependencies": tuple(parsed_dependencies),
        "assumptions": tuple(assumptions),
    }


def _parse_raw_plan(
    raw: dict[str, Any], max_steps: int
) -> tuple[tuple[ProposedTask, ...], tuple[tuple[str, str], ...], tuple[str, ...]]:
    # _extract_and_validate_plan returns a normalized dict; this helper just
    # unpacks it so callers don't have to index into the raw result.
    tasks = raw["tasks"]
    dependencies = raw["dependencies"]
    assumptions = raw["assumptions"]
    return tasks, dependencies, assumptions


def _collect_method_references(
    tasks: tuple[ProposedTask, ...],
    method_library: tuple["EngineeringMethod", ...],
) -> tuple[str, ...]:
    """Return the de-duplicated method_refs attached to ``tasks``.

    F-151: this is the *plan-level* roll-up of ``lkbMetadata.method_ref``
    values.  Order follows first occurrence; the values are *not* filtered
    by method-library membership — the F-150 rule engine
    (``validate_method_compliance``) already emits an R-METHOD-UNKNOWN
    warning for any value not present in the library, so the plan can
    surface unrecognised refs verbatim for the audit trail.

    Parameters
    ----------
    tasks:
        The parsed :class:`ProposedTask` list.
    method_library:
        The library snapshot the decomposer was constructed with.  Only
        the type is consulted — this helper itself does not validate
        membership.
    """
    seen: list[str] = []
    for task in tasks:
        method_ref = task.lkb_metadata.get("method_ref")
        if not isinstance(method_ref, str):
            continue
        if not method_ref.strip():
            continue
        if method_ref in seen:
            continue
        seen.append(method_ref)
    return tuple(seen)


def _count_method_task_usage(
    tasks: tuple[ProposedTask, ...],
) -> dict[str, int]:
    """Return a ``method_ref -> task_count`` map for F-151 audit events."""
    counts: dict[str, int] = {}
    for task in tasks:
        method_ref = task.lkb_metadata.get("method_ref")
        if not isinstance(method_ref, str) or not method_ref.strip():
            continue
        counts[method_ref] = counts.get(method_ref, 0) + 1
    return counts


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise TaskDecompositionError(
            f"{where} contains unknown fields: {', '.join(unknown)}"
        )


def _require_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaskDecompositionError(f"{where}.{key} must be a non-empty string")
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def _validate_lkb_metadata(lkb: dict[str, Any], where: str) -> None:
    _reject_unknown_keys(lkb, _LKB_METADATA_KEYS, where)
    if "strict_acceptance" in lkb and not isinstance(lkb["strict_acceptance"], bool):
        raise TaskDecompositionError(f"{where}.strict_acceptance must be a boolean")
    for key in ("assertions", "assumptions"):
        if key in lkb and not isinstance(lkb[key], list):
            raise TaskDecompositionError(f"{where}.{key} must be a list")
        if key in lkb:
            for idx, item in enumerate(lkb[key]):
                if not isinstance(item, str):
                    raise TaskDecompositionError(
                        f"{where}.{key}[{idx}] must be a string"
                    )
    if "acceptance_proof" in lkb and not isinstance(lkb["acceptance_proof"], (str, type(None))):
        raise TaskDecompositionError(f"{where}.acceptance_proof must be a string or null")
    # F-150: ``method_ref`` is optional; if present, it must be a non-empty
    # string.  We do not enforce method-library membership here — that is the
    # job of R-METHOD-UNKNOWN in ``validate_method_compliance``.
    if "method_ref" in lkb:
        method_ref = lkb["method_ref"]
        if not isinstance(method_ref, str) or not method_ref.strip():
            raise TaskDecompositionError(
                f"{where}.method_ref must be a non-empty string when present"
            )
    # F-152: ``scheduling_required`` is optional; when present it must be
    # a boolean.  The flag is informational at the task level — the
    # actual scheduling parameters live in
    # ``DecompositionPlan.scheduling_constraints`` (set by the caller).
    if "scheduling_required" in lkb and not isinstance(
        lkb["scheduling_required"], bool
    ):
        raise TaskDecompositionError(
            f"{where}.scheduling_required must be a boolean when present"
        )
    # F-152: ``duration`` (positive int) and ``earliest_start``
    # (non-negative int) are optional per-task scheduling hints.  The
    # LKB scheduling pass picks them up to build a SchedulingTask.
    if "duration" in lkb and (
        not isinstance(lkb["duration"], int) or isinstance(lkb["duration"], bool)
        or lkb["duration"] < 1
    ):
        raise TaskDecompositionError(
            f"{where}.duration must be a positive integer when present"
        )
    if "earliest_start" in lkb and (
        not isinstance(lkb["earliest_start"], int)
        or isinstance(lkb["earliest_start"], bool)
        or lkb["earliest_start"] < 0
    ):
        raise TaskDecompositionError(
            f"{where}.earliest_start must be a non-negative integer when present"
        )


__all__ = [
    "DecompositionPlan",
    "ProposedTask",
    "TaskDecomposer",
    "TaskDecompositionError",
]
