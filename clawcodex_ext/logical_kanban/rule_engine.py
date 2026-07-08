"""Layer-1 in-process rule engine for Logical Kanban.

The engine evaluates the six MVP rules defined in F-132 synchronously,
without external solvers. It consumes a :class:`FactsSnapshot` produced by
``context_adapter.build_facts_snapshot`` and returns deterministic derived
facts plus proof traces for every denial.

F-150 adds :meth:`Layer1RuleEngine.validate_method_compliance` which
evaluates three method-library rules (R-METHOD-001/002/003) against a
:class:`~.decomposer.DecompositionPlan`. Those rules emit ``warning``-level
:class:`~.types.ValidationIssue` entries — they never block the commit
during the MVP phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .types import FactsSnapshot, ValidationIssue

if TYPE_CHECKING:
    from .decomposer import DecompositionPlan
    from .method_library import EngineeringMethod
    from clawcodex_ext.tool_system.context import ToolContext


@dataclass(frozen=True)
class RuleEngineResult:
    """Result of a Layer-1 rule-engine evaluation."""

    result: Literal["pass", "fail"]
    derived_facts: tuple[str, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()
    violated_rule: str | None = None
    cycle_tasks: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "result": self.result,
            "derivedFacts": list(self.derived_facts),
            "proofTrace": list(self.proof_trace),
        }
        if self.violated_rule is not None:
            out["violatedRule"] = self.violated_rule
        if self.cycle_tasks:
            out["cycleTasks"] = list(self.cycle_tasks)
        if self.message:
            out["message"] = self.message
        return out


@dataclass(frozen=True)
class _DerivedFact:
    fact: str
    rule: str
    premises: tuple[str, ...]
    conclusion: str


class Layer1RuleEngine:
    """Synchronous rule engine implementing the F-132 MVP rule set."""

    solver_version = "lkb-layer1-v1"

    def from_context(self, context: "ToolContext") -> FactsSnapshot:
        """Build a deterministic facts snapshot from a tool context."""
        from .context_adapter import build_facts_snapshot

        return build_facts_snapshot(context)

    def evaluate(
        self,
        snapshot: FactsSnapshot,
        *,
        target_task_id: str | None = None,
        target_status: str | None = None,
        strict_acceptance: bool = False,
        acceptance_proof_present: bool | None = None,
    ) -> RuleEngineResult:
        """Derive facts and, optionally, answer a transition query.

        Parameters
        ----------
        snapshot:
            Current facts snapshot.
        target_task_id:
            Optional task being asked to move.
        target_status:
            Optional target status for the query (``pending``, ``in_progress``,
            or ``completed``).
        strict_acceptance:
            Whether R-005 (acceptance proof required for Done) is active.
        acceptance_proof_present:
            Whether the target task already carries an acceptance proof. When
            ``None``, the engine derives this from ``snapshot.facts``.
        """
        derived = self._derive_all_facts(
            snapshot,
            strict_acceptance=strict_acceptance,
            target_task_id=target_task_id,
            target_status=target_status,
            acceptance_proof_present=acceptance_proof_present,
        )

        if target_task_id is None or target_status is None:
            return self._pass(derived)

        task = snapshot.normalized_tasks.get(target_task_id)
        if task is None:
            return self._pass(derived)

        if target_status == "in_progress":
            return self._evaluate_in_progress(snapshot, derived, target_task_id)

        if target_status == "completed":
            return self._evaluate_completed(
                snapshot,
                derived,
                target_task_id,
                strict_acceptance=strict_acceptance,
                acceptance_proof_present=acceptance_proof_present,
            )

        # ``pending`` and any other transition are allowed by Layer-1.
        derived.append(
            _DerivedFact(
                fact=f"CanMoveTo({target_task_id}, {target_status})",
                rule="LAYER1-ALLOW",
                premises=(f"Task({target_task_id})",),
                conclusion=f"CanMoveTo({target_task_id}, {target_status})",
            )
        )
        return self._pass(derived)

    def _derive_all_facts(
        self,
        snapshot: FactsSnapshot,
        *,
        strict_acceptance: bool,
        target_task_id: str | None,
        target_status: str | None,
        acceptance_proof_present: bool | None,
    ) -> list[_DerivedFact]:
        derived: list[_DerivedFact] = []
        task_ids = sorted(snapshot.normalized_tasks)

        for task_id in task_ids:
            task = snapshot.normalized_tasks[task_id]
            status = task["status"]

            if task_id in snapshot.cycle_task_ids:
                cycle_tasks = sorted(snapshot.cycle_task_ids)
                derived.append(
                    _DerivedFact(
                        fact=f"Cycle({task_id})",
                        rule="R-006",
                        premises=tuple(f"Cycle({t})" for t in cycle_tasks),
                        conclusion=f"Cycle({task_id})",
                    )
                )
                derived.append(
                    _DerivedFact(
                        fact=f"NotReady({task_id})",
                        rule="R-006",
                        premises=tuple(f"Cycle({t})" for t in cycle_tasks),
                        conclusion=f"NotReady({task_id})",
                    )
                )
                derived.append(
                    _DerivedFact(
                        fact=f"NotCanMoveTo({task_id}, in_progress)",
                        rule="R-006",
                        premises=tuple(f"Cycle({t})" for t in cycle_tasks),
                        conclusion=f"NotCanMoveTo({task_id}, in_progress)",
                    )
                )
                continue

            if task_id in snapshot.blocked_ids:
                active_blockers = [
                    b
                    for b in snapshot.blocked_by.get(task_id, ())
                    if b not in snapshot.completed_ids
                ]
                premises: list[str] = []
                for blocker in sorted(active_blockers):
                    premises.append(f"Requires({blocker}, {task_id})")
                    premises.append(f"NotDone({blocker})")
                premises.append(f"NotDone({task_id})")
                derived.append(
                    _DerivedFact(
                        fact=f"Blocked({task_id})",
                        rule="R-001",
                        premises=tuple(premises),
                        conclusion=f"Blocked({task_id})",
                    )
                )
                derived.append(
                    _DerivedFact(
                        fact=f"NotCanMoveTo({task_id}, in_progress)",
                        rule="R-002",
                        premises=(f"Blocked({task_id})",),
                        conclusion=f"NotCanMoveTo({task_id}, in_progress)",
                    )
                )
                continue

            if status == "pending":
                derived.append(
                    _DerivedFact(
                        fact=f"Ready({task_id})",
                        rule="R-003",
                        premises=(
                            f"Status({task_id}, pending)",
                            f"NotBlocked({task_id})",
                        ),
                        conclusion=f"Ready({task_id})",
                    )
                )
                derived.append(
                    _DerivedFact(
                        fact=f"CanMoveTo({task_id}, in_progress)",
                        rule="R-004",
                        premises=(f"Ready({task_id})",),
                        conclusion=f"CanMoveTo({task_id}, in_progress)",
                    )
                )

            if status == "in_progress":
                derived.append(
                    _DerivedFact(
                        fact=f"Doing({task_id})",
                        rule="LAYER1-FACT",
                        premises=(f"Status({task_id}, in_progress)",),
                        conclusion=f"Doing({task_id})",
                    )
                )

            if status == "completed":
                derived.append(
                    _DerivedFact(
                        fact=f"Done({task_id})",
                        rule="LAYER1-FACT",
                        premises=(f"Status({task_id}, completed)",),
                        conclusion=f"Done({task_id})",
                    )
                )

            # R-005: if strict acceptance is enabled and we are evaluating a
            # completion, surface acceptance-proof facts now. The actual denial
            # is handled in ``_evaluate_completed``.
            if strict_acceptance and target_task_id == task_id and target_status == "completed":
                has_proof = self._resolve_acceptance_proof(
                    snapshot, task_id, acceptance_proof_present
                )
                if has_proof:
                    derived.append(
                        _DerivedFact(
                            fact=f"HasAcceptanceProof({task_id})",
                            rule="R-005",
                            premises=(
                                f"StrictAcceptance({task_id})",
                                f"HasAcceptanceProof({task_id})",
                            ),
                            conclusion=f"HasAcceptanceProof({task_id})",
                        )
                    )

        return derived

    def _evaluate_in_progress(
        self,
        snapshot: FactsSnapshot,
        derived: list[_DerivedFact],
        task_id: str,
    ) -> RuleEngineResult:
        if task_id in snapshot.cycle_task_ids:
            cycle_tasks = sorted(snapshot.cycle_task_ids)
            return RuleEngineResult(
                result="fail",
                violated_rule="R-006",
                cycle_tasks=tuple(cycle_tasks),
                message=(
                    f"Task {task_id} cannot enter in_progress because its "
                    f"readiness depends on a cyclic dependency chain: "
                    f"{', '.join(cycle_tasks)}."
                ),
                derived_facts=self._facts_of(derived),
                proof_trace=self._proof_trace_of(derived),
            )

        if task_id in snapshot.blocked_ids:
            blockers = [
                b for b in snapshot.blocked_by.get(task_id, ()) if b not in snapshot.completed_ids
            ]
            return RuleEngineResult(
                result="fail",
                violated_rule="R-002",
                message=(
                    f"Task {task_id} cannot enter in_progress because active "
                    f"blockers remain: {', '.join(sorted(blockers))}."
                ),
                derived_facts=self._facts_of(derived),
                proof_trace=self._proof_trace_of(derived),
            )

        return self._pass(derived)

    def _evaluate_completed(
        self,
        snapshot: FactsSnapshot,
        derived: list[_DerivedFact],
        task_id: str,
        *,
        strict_acceptance: bool,
        acceptance_proof_present: bool | None,
    ) -> RuleEngineResult:
        if strict_acceptance:
            has_proof = self._resolve_acceptance_proof(snapshot, task_id, acceptance_proof_present)
            if not has_proof:
                denial_fact = _DerivedFact(
                    fact=f"NotCanMoveTo({task_id}, completed)",
                    rule="R-005",
                    premises=(
                        f"StrictAcceptance({task_id})",
                        f"Not(HasAcceptanceProof({task_id}))",
                    ),
                    conclusion=f"NotCanMoveTo({task_id}, completed)",
                )
                return RuleEngineResult(
                    result="fail",
                    violated_rule="R-005",
                    message=(
                        f"Task {task_id} cannot enter completed because strict "
                        "acceptance is enabled and no acceptance proof is present."
                    ),
                    derived_facts=self._facts_of([*derived, denial_fact]),
                    proof_trace=self._proof_trace_of([*derived, denial_fact]),
                )
            derived.append(
                _DerivedFact(
                    fact=f"CanMoveTo({task_id}, completed)",
                    rule="R-005",
                    premises=(
                        f"StrictAcceptance({task_id})",
                        f"HasAcceptanceProof({task_id})",
                    ),
                    conclusion=f"CanMoveTo({task_id}, completed)",
                )
            )
            return self._pass(derived)

        derived.append(
            _DerivedFact(
                fact=f"CanMoveTo({task_id}, completed)",
                rule="LAYER1-ALLOW",
                premises=(f"Task({task_id})",),
                conclusion=f"CanMoveTo({task_id}, completed)",
            )
        )
        return self._pass(derived)

    def _resolve_acceptance_proof(
        self,
        snapshot: FactsSnapshot,
        task_id: str,
        acceptance_proof_present: bool | None,
    ) -> bool:
        if acceptance_proof_present is not None:
            return acceptance_proof_present
        return f"HasAcceptanceProof({task_id})" in snapshot.facts

    def _pass(self, derived: list[_DerivedFact]) -> RuleEngineResult:
        return RuleEngineResult(
            result="pass",
            derived_facts=self._facts_of(derived),
            proof_trace=self._proof_trace_of(derived),
        )

    def _facts_of(self, derived: list[_DerivedFact]) -> tuple[str, ...]:
        return tuple(sorted({d.fact for d in derived}))

    def _proof_trace_of(self, derived: list[_DerivedFact]) -> tuple[dict[str, Any], ...]:
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        traces: list[dict[str, Any]] = []
        for d in derived:
            key = (d.rule, d.conclusion, d.premises)
            if key in seen:
                continue
            seen.add(key)
            traces.append(
                {
                    "rule": d.rule,
                    "premises": list(d.premises),
                    "conclusion": d.conclusion,
                    "solverVersion": self.solver_version,
                }
            )
        return tuple(traces)


def evaluate_rules(
    snapshot: FactsSnapshot,
    *,
    target_task_id: str | None = None,
    target_status: str | None = None,
    strict_acceptance: bool = False,
    acceptance_proof_present: bool | None = None,
) -> RuleEngineResult:
    """Convenience entry point for one-shot rule evaluation."""
    return Layer1RuleEngine().evaluate(
        snapshot,
        target_task_id=target_task_id,
        target_status=target_status,
        strict_acceptance=strict_acceptance,
        acceptance_proof_present=acceptance_proof_present,
    )


# ---------------------------------------------------------------------------
# F-150: method-library compliance (R-METHOD-001 / 002 / 003)
# ---------------------------------------------------------------------------


import re as _re

_SLOT_FINDER = _re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def _strip_slots(template: str) -> str:
    """Return ``template`` with all ``{slot}`` markers removed.

    Used by R-METHOD-003 to canonicalize an acceptance-template assertion
    so that we can do a substring match against the task's
    ``lkbMetadata.assertions`` without worrying about unfilled placeholders.
    """
    return _SLOT_FINDER.sub("", template).strip()


def _resolve_method(
    method_id: str, library: tuple["EngineeringMethod", ...] | None
) -> "EngineeringMethod | None":
    if not library:
        return None
    for method in library:
        if method.method_id == method_id:
            return method
    return None


def validate_method_compliance(
    plan: "DecompositionPlan",
    *,
    method_library: tuple["EngineeringMethod", ...] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Evaluate R-METHOD-001/002/003 against ``plan`` and return any issues.

    All issues are emitted with ``severity="warning"`` per the F-150 design
    decision (MVP phase: methods are guidance, not hard constraints).  The
    caller (typically :class:`~.decomposer.TaskDecomposer`) decides whether
    to surface these issues inside its :class:`~.types.ValidationRun`.

    Rules
    -----
    R-METHOD-001
        For each ``ProposedTask`` that references a known method via
        ``lkbMetadata.method_ref``, the *total* number of tasks referring
        to that method must match ``method.subtask_templates`` length.  If
        only a subset is present (typical mid-decomposition state) the
        issue mentions the missing count.

    R-METHOD-002
        Every entry in ``method.preconditions`` must be reflected in
        either ``plan.assumptions`` or the union of
        ``task.lkbMetadata.assumptions`` across tasks referencing this
        method.  Mismatches are surfaced as warnings so the user can decide
        whether to add the assumption or drop the method reference.

    R-METHOD-003
        When ``method.acceptance_template.strict_acceptance`` is true, the
        rendered (slot-stripped) ``assertion_template`` must appear in the
        union of ``task.lkbMetadata.assertions`` for tasks referencing this
        method.  This guards against silent acceptance regressions where
        the LLM skips the documented assertion.
    """
    # Lazy imports keep rule_engine importable from contexts that have not
    # yet loaded method_library (e.g. circular-import-safe unit tests).
    from .decomposer import DecompositionPlan  # type: ignore[attr-defined]

    issues: list[ValidationIssue] = []
    if not isinstance(plan, DecompositionPlan):
        raise TypeError("validate_method_compliance expects a DecompositionPlan")

    if method_library is None:
        try:
            from .method_library import get_all_methods
        except ImportError:  # pragma: no cover - defensive
            return ()
        method_library = get_all_methods()

    # Bucket tasks by method_ref so we can count subtasks per method.
    by_method: dict[str, list[Any]] = {}
    for task in plan.tasks:
        method_ref = task.lkb_metadata.get("method_ref") if task.lkb_metadata else None
        if not isinstance(method_ref, str) or not method_ref:
            continue
        by_method.setdefault(method_ref, []).append(task)

    if not by_method:
        return ()

    plan_assumptions = " ".join(plan.assumptions).lower()

    for method_id, tasks in by_method.items():
        method = _resolve_method(method_id, method_library)
        if method is None:
            issues.append(
                ValidationIssue(
                    code="R-METHOD-UNKNOWN",
                    message=(
                        f"Task(s) reference unknown method_id {method_id!r}; "
                        "R-METHOD-001/002/003 skipped for this reference."
                    ),
                    rule="R-METHOD-001",
                    severity="warning",
                )
            )
            continue

        # R-METHOD-001 — task count vs subtask template count.
        expected = len(method.subtask_templates)
        actual = len(tasks)
        if actual < expected:
            missing = expected - actual
            issues.append(
                ValidationIssue(
                    code="R-METHOD-001-INCOMPLETE",
                    message=(
                        f"Method {method_id!r} expects {expected} subtask "
                        f"templates but only {actual} tasks reference it "
                        f"(missing at least {missing})."
                    ),
                    rule="R-METHOD-001",
                    severity="warning",
                    task_id=tasks[-1].proposed_task_id,
                )
            )

        # Aggregate task-level assumptions and assertions.
        task_assumptions: list[str] = []
        task_assertions: list[str] = []
        for task in tasks:
            meta = task.lkb_metadata or {}
            for assumption in meta.get("assumptions") or ():
                if isinstance(assumption, str) and assumption:
                    task_assumptions.append(assumption)
            for assertion in meta.get("assertions") or ():
                if isinstance(assertion, str) and assertion:
                    task_assertions.append(assertion)
        task_assumption_blob = " ".join(task_assumptions).lower()

        # R-METHOD-002 — preconditions must be reflected in assumptions.
        for precondition in method.preconditions:
            lowered = precondition.lower()
            if lowered in plan_assumptions or lowered in task_assumption_blob:
                continue
            # Best-effort token overlap — check at least one 5+ char token
            # from the precondition shows up in any assumption.
            tokens = [t for t in lowered.split() if len(t) >= 5]
            if any(token in task_assumption_blob or token in plan_assumptions for token in tokens):
                continue
            issues.append(
                ValidationIssue(
                    code="R-METHOD-002-PRECONDITION",
                    message=(
                        f"Method {method_id!r} precondition {precondition!r} "
                        "is not reflected in plan.assumptions or task "
                        "lkbMetadata.assumptions."
                    ),
                    rule="R-METHOD-002",
                    severity="warning",
                    task_id=tasks[0].proposed_task_id,
                )
            )

        # R-METHOD-003 — strict acceptance assertion must be present.
        if method.acceptance_template is not None and method.acceptance_template.strict_acceptance:
            canonical = _strip_slots(method.acceptance_template.assertion_template)
            canonical_lower = canonical.lower()
            # Match either as a substring, or as the prefix before any
            # parenthesis — this lets the LLM fill in slots inline
            # (``EndpointContractStable(/api/v1/things)`` matches
            # ``EndpointContractStable({route})``).
            canonical_prefix = canonical_lower.split("(", 1)[0].strip()
            assertion_blob = " ".join(task_assertions).lower()
            matched = bool(canonical_lower) and (
                canonical_lower in assertion_blob
                or (canonical_prefix and canonical_prefix in assertion_blob)
            )
            if not matched:
                issues.append(
                    ValidationIssue(
                        code="R-METHOD-003-ASSERTION",
                        message=(
                            f"Method {method_id!r} has strict_acceptance but "
                            f"no task assertion matches {canonical!r}."
                        ),
                        rule="R-METHOD-003",
                        severity="warning",
                        task_id=tasks[0].proposed_task_id,
                    )
                )

    return tuple(issues)


def validate_external_config_references(
    plan: "DecompositionPlan",
    *,
    operations: tuple[Any, ...] | None = None,
    ontology: Any | None = None,
) -> tuple[ValidationIssue, ...]:
    """Evaluate F-154 R-METHOD-004/005 external config rules."""

    from .decomposer import DecompositionPlan  # type: ignore[attr-defined]
    from .operation_schema import get_all_operation_schemas, predicate_name
    from .ontology_graph import get_registered_ontology

    if not isinstance(plan, DecompositionPlan):
        raise TypeError("validate_external_config_references expects a DecompositionPlan")

    if operations is None:
        operations = get_all_operation_schemas()
    if ontology is None:
        ontology = get_registered_ontology()

    issues: list[ValidationIssue] = []
    operation_ids = {
        operation.operation_id for operation in operations if hasattr(operation, "operation_id")
    }

    if operation_ids:
        for task in plan.tasks:
            meta = task.lkb_metadata or {}
            for assumption in meta.get("assumptions") or ():
                if not isinstance(assumption, str):
                    continue
                for operation_id in _external_operation_ids(assumption):
                    if operation_id not in operation_ids:
                        issues.append(
                            ValidationIssue(
                                code="R-METHOD-004-UNKNOWN-OPERATION",
                                message=(
                                    f"Task {task.proposed_task_id} references operation "
                                    f"{operation_id!r}, but no loaded OperationSchema defines it."
                                ),
                                rule="R-METHOD-004",
                                severity="error",
                                task_id=task.proposed_task_id,
                            )
                        )

    if ontology is not None and getattr(ontology, "classes", None):
        classes = set(ontology.classes)
        for task in plan.tasks:
            meta = task.lkb_metadata or {}
            for assertion in meta.get("assertions") or ():
                if not isinstance(assertion, str):
                    continue
                class_name = predicate_name(assertion)
                if class_name and class_name not in classes:
                    issues.append(
                        ValidationIssue(
                            code="R-METHOD-005-UNKNOWN-ONTOLOGY-CLASS",
                            message=(
                                f"Task {task.proposed_task_id} assertion {assertion!r} "
                                f"references ontology class {class_name!r}, but it is not loaded."
                            ),
                            rule="R-METHOD-005",
                            severity="warning",
                            task_id=task.proposed_task_id,
                        )
                    )
    return tuple(issues)


def validate_acceptance_template_references(
    plan: "DecompositionPlan",
    *,
    templates: tuple[Any, ...] | None = None,
) -> tuple[ValidationIssue, ...]:
    """Evaluate F-155 R-METHOD-006 acceptance-template reference rules."""

    from .decomposer import DecompositionPlan  # type: ignore[attr-defined]
    from .acceptance_template import get_all_acceptance_templates

    if not isinstance(plan, DecompositionPlan):
        raise TypeError("validate_acceptance_template_references expects a DecompositionPlan")

    if templates is None:
        templates = get_all_acceptance_templates()

    known_ids = {template.template_id for template in templates if hasattr(template, "template_id")}
    issues: list[ValidationIssue] = []
    for task in plan.tasks:
        for template_id in _acceptance_template_refs_for_task(task):
            if template_id not in known_ids:
                issues.append(
                    ValidationIssue(
                        code="R-METHOD-006-UNKNOWN-ACCEPTANCE-TEMPLATE",
                        message=(
                            f"Task {task.proposed_task_id} references acceptance template "
                            f"{template_id!r}, but no loaded AcceptanceTemplate defines it."
                        ),
                        rule="R-METHOD-006",
                        severity="warning",
                        task_id=task.proposed_task_id,
                    )
                )
    return tuple(issues)


def _external_operation_ids(text: str) -> tuple[str, ...]:
    return tuple(_re.findall(r"\bOP-[a-z0-9]+(?:-[a-z0-9]+)*\b", text))


def acceptance_template_refs_for_plan(plan: "DecompositionPlan") -> tuple[str, ...]:
    seen: list[str] = []
    for task in plan.tasks:
        for template_id in _acceptance_template_refs_for_task(task):
            if template_id not in seen:
                seen.append(template_id)
    return tuple(seen)


def _acceptance_template_refs_for_task(task: Any) -> tuple[str, ...]:
    meta = getattr(task, "lkb_metadata", {}) or {}
    refs: list[str] = []
    for key in ("acceptance_template_id", "acceptance_template_ref", "template_ref"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            refs.append(value.strip())
    for assertion in meta.get("assertions") or ():
        if not isinstance(assertion, str):
            continue
        refs.extend(_acceptance_template_ids(assertion))
    out: list[str] = []
    for ref in refs:
        if ref not in out:
            out.append(ref)
    return tuple(out)


def _acceptance_template_ids(text: str) -> tuple[str, ...]:
    refs = []
    refs.extend(_re.findall(r"\btemplate_ref\s*[:=]\s*(T-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3})\b", text))
    refs.extend(
        _re.findall(r"\bacceptance_template_id\s*[:=]\s*(T-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3})\b", text)
    )
    return tuple(refs)
