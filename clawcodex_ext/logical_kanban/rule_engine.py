"""Layer-1 in-process rule engine for Logical Kanban.

The engine evaluates the six MVP rules defined in F-132 synchronously,
without external solvers. It consumes a :class:`FactsSnapshot` produced by
``context_adapter.build_facts_snapshot`` and returns deterministic derived
facts plus proof traces for every denial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .types import FactsSnapshot

if TYPE_CHECKING:
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
            return self._evaluate_in_progress(
                snapshot, derived, target_task_id
            )

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
                    b for b in snapshot.blocked_by.get(task_id, ()) if b not in snapshot.completed_ids
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
            if (
                strict_acceptance
                and target_task_id == task_id
                and target_status == "completed"
            ):
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
            has_proof = self._resolve_acceptance_proof(
                snapshot, task_id, acceptance_proof_present
            )
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
