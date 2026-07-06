"""Synchronous Logical Kanban foundation service."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from .ambiguity_detector import AmbiguityDetector
from .causal import (
    CausalEffect,
    CausalEngine,
    CausalGraph,
    CausalMechanism,
    SIGNIFICANT_THRESHOLD,
    build_causal_graph,
    is_strict_causal_enabled,
)
from .commit_gate_fuzzy import aggregate_world_results, commit_gate_fuzzy_check
from . import metrics
from .audit import (
    AuditEvent,
    AuditLog,
    append_proof_enrichment_once,
    event_for_assumption_invalidated,
    event_for_commit,
    event_for_human_override,
    event_for_legacy_todo_ambiguity,
    event_for_proof_enrichment,
    event_for_proposal,
    event_for_revalidation_requested,
    event_for_validation_run,
    get_audit_log,
)
from .flags import is_causal_verification_enabled, is_llm_facts_enabled, is_logical_kanban_enabled
from .context_adapter import active_blockers, build_facts_snapshot, dependency_closure
from .explain import build_repair_suggestions
from .fuzzy_types import (
    AggregationDecision,
    Ambiguity,
    AmbiguityReport,
    CommitDecision,
    MultiWorldResult,
    Severity,
    World,
)
from .glossary import BUILT_IN_GLOSSARY
from .ir_hash import canonical_hash
from .multiworld_validator import MultiWorldValidator
from .rule_engine import Layer1RuleEngine
from .runtime import get_logical_kanban
from .solver_adapter import SolverAdapter, SolverRequest
from .solver_pipeline import SolverPipeline
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
    from .fuzzy_patterns import FuzzyPatternLibrary
    from .fuzzy_types import Clarification
    from .ir import CanonicalAssertion
    from .truth_maintenance import AssumptionRecord


_LAYER1_RULESET = {
    'name': 'lkb-layer1-mvp',
    'version': '1.0.0',
    'engine': 'layer1-python',
    'rules': [
        {'id': 'R-001', 'description': 'Blocked(T) when active prerequisites remain'},
        {'id': 'R-002', 'description': 'Blocked task cannot enter in_progress'},
        {'id': 'R-003', 'description': 'Ready(T) when pending and not blocked'},
        {'id': 'R-004', 'description': 'CanMoveTo(T, in_progress) when Ready(T)'},
        {'id': 'R-005', 'description': 'Done requires acceptance proof in strict mode'},
        {'id': 'R-006', 'description': 'Cyclic dependency invalidates readiness'},
    ],
}
_RULESET_HASH = canonical_hash(_LAYER1_RULESET)


def _new_id(prefix: str) -> str:
    return f'{prefix}{uuid.uuid4().hex[:12]}'


def _session_id(context: 'ToolContext') -> str | None:
    return getattr(context, 'session_id', None) or None


def _audit_log(context: 'ToolContext') -> AuditLog:
    return get_audit_log(context)


def _severity_rank(severity: Severity) -> int:
    return {'negligible': 0, 'minor': 1, 'major': 2, 'critical': 3}[severity]


def _select_ambiguity_entry(report: AmbiguityReport) -> Ambiguity | None:
    """Return the highest-severity ambiguity in ``report``."""
    if not report.detected_ambiguities:
        return None
    return max(report.detected_ambiguities, key=lambda a: _severity_rank(a.severity))


def _legacy_todo_ambiguity_dict(todo_id: str, report: AmbiguityReport) -> dict[str, Any]:
    """Build the F-144 ambiguity payload for a single todo."""
    entry = _select_ambiguity_entry(report)
    return {
        'todoId': todo_id,
        'ambiguityCode': entry.pattern_id if entry else '',
        'severity': report.severity,
        'clarificationPrompt': entry.clarification_prompt if entry else '',
    }


def _legacy_todo_denial_message(
    ambiguities: tuple[dict[str, Any], ...],
    commit_decision: CommitDecision | None,
) -> str:
    """Build a human-readable denial message for ambiguous legacy todos."""
    if commit_decision is not None and not commit_decision.commit:
        return commit_decision.human_message.get(
            'en', 'Legacy TodoWrite contains ambiguous content that must be clarified.'
        )
    return 'Legacy TodoWrite contains ambiguous content that must be clarified.'


def _string_list(value: Any) -> tuple[str, ...]:
    """Return ``value`` if it's a list of strings, else an empty tuple."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _task_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    task_id = payload.get('taskId')
    return task_id if isinstance(task_id, str) else None


class LogicalKanbanService:
    """Internal propose/validate/commit service for task-state changes."""

    solver_version = 'lkb-foundation-sync-v1'

    def __init__(
        self,
        llm_provider: Any = None,
        pattern_library: 'FuzzyPatternLibrary | None' = None,
    ) -> None:
        from .fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY

        self.engine = Layer1RuleEngine()
        self.pipeline = SolverPipeline()
        self.causal_engine = CausalEngine()
        self._llm_provider = llm_provider
        # F-148: the default library carries zero scenario-bound
        # interpretations.  Deployments that need a concrete
        # ``on_foot / straight_line / by_vehicle`` (or any other) split
        # pass it via the ``pattern_library`` constructor argument;
        # ``library.add(...)`` chains are the supported wiring.
        self._pattern_library = pattern_library or BUILT_IN_PATTERN_LIBRARY

    def snapshot(self, context: 'ToolContext') -> FactsSnapshot:
        return build_facts_snapshot(context)

    def _augmented_snapshot(self, context: 'ToolContext') -> FactsSnapshot:
        """Return a snapshot possibly enriched with LLM-derived facts (F-143 L1).

        When the feature flag is off or no provider is configured, this is a
        thin wrapper around :meth:`snapshot` with no extra latency.
        """
        snapshot = self.snapshot(context)
        if not is_llm_facts_enabled() or self._llm_provider is None:
            return snapshot
        from .llm_fact_extractor import LlmFactExtractor

        extractor = LlmFactExtractor(provider=self._llm_provider)
        extracted = extractor.run(
            snapshot,
            BUILT_IN_GLOSSARY,
            audit_log=_audit_log(context),
        )
        if extracted:
            return replace(snapshot, facts=(*snapshot.facts, *extracted))
        return snapshot

    def propose(self, change: ProposedChange, context: 'ToolContext') -> Proposal:
        snapshot = self.snapshot(context)
        proposal = Proposal(
            proposal_id=_new_id('P-'),
            change=change,
            snapshot_hash=snapshot.hash,
        )
        _audit_log(context).append(event_for_proposal(proposal, session_id=_session_id(context)))
        return proposal

    def validate(self, proposal: Proposal, context: 'ToolContext') -> ValidationRun:
        start = time.perf_counter()
        run = self._do_validate(proposal, context)
        duration_ms = int((time.perf_counter() - start) * 1000)
        run = replace(run, duration_ms=max(duration_ms, 0))
        _audit_log(context).append(
            event_for_validation_run(proposal, run, session_id=_session_id(context))
        )
        task_count = len(getattr(context, 'tasks', {}) or {})
        metrics.record_validation_run(
            result=run.result,
            engine=run.engine,
            change_kind=proposal.change.kind,
            duration_ms=run.duration_ms,
            task_count=task_count,
            task_id=run.task_id,
            validation_run_id=run.validation_run_id,
            proposal_id=proposal.proposal_id,
        )
        self._emit_snapshot_metrics(context)
        return run

    async def validate_async(
        self,
        proposal: Proposal,
        context: 'ToolContext',
        *,
        adapters: tuple[SolverAdapter, ...] | list[SolverAdapter] | None = None,
        timeout_seconds: float = 60.0,
    ) -> ValidationRun:
        """Run optional proof enrichment without blocking the sync commit path."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._validate_async_blocking,
                    proposal,
                    context,
                    tuple(adapters) if adapters is not None else None,
                    timeout_seconds,
                ),
                timeout=timeout_seconds + 1.0,
            )
        except Exception as exc:  # noqa: BLE001 - async enrichment must not leak
            return ValidationRun(
                validation_run_id=_new_id('V-'),
                proposal_id=proposal.proposal_id,
                task_id=_task_id_from_payload(proposal.change.payload),
                input_facts_hash=proposal.snapshot_hash,
                ruleset_hash=_RULESET_HASH,
                snapshot_hash=proposal.snapshot_hash,
                engine='external-atp-async',
                engine_version='',
                result='error',
                duration_ms=0,
                created_at=datetime.now(timezone.utc).isoformat(),
                requested_by=proposal.change.actor or 'system',
                solver_results=(
                    {
                        'adapter': 'external-atp-async',
                        'result': 'error',
                        'errorInfo': {
                            'reason': 'exception',
                            'exception': type(exc).__name__,
                            'detail': str(exc),
                        },
                    },
                ),
            )

    def _validate_async_blocking(
        self,
        proposal: Proposal,
        context: 'ToolContext',
        adapters: tuple[SolverAdapter, ...] | None,
        timeout_seconds: float,
    ) -> ValidationRun:
        if proposal.change.kind != 'transition_status':
            return self.validate(proposal, context)

        payload = proposal.change.payload
        task_id = payload.get('taskId')
        target_status = payload.get('status')
        snapshot = self.snapshot(context)
        task = snapshot.normalized_tasks.get(task_id) if isinstance(task_id, str) else None
        if not isinstance(task_id, str) or not isinstance(target_status, str) or task is None:
            return self.validate(proposal, context)

        if adapters is None:
            from .atp import Mace4SolverAdapter, Prover9SolverAdapter, VampireSolverAdapter

            adapters = (
                VampireSolverAdapter(),
                Prover9SolverAdapter(),
                Mace4SolverAdapter(),
            )
            adapters = tuple(adapter for adapter in adapters if adapter.available())

        request = SolverRequest(
            snapshot=snapshot,
            target_task_id=task_id,
            target_status=target_status,
            strict_acceptance=(
                self._strict_acceptance_enabled(context, task, payload)
                if target_status == 'completed'
                else False
            ),
            acceptance_proof_present=(
                self._has_acceptance_proof(task, payload)
                if target_status == 'completed'
                else None
            ),
        )

        run = SolverPipeline(adapters).validate(
            request,
            proposal_id=proposal.proposal_id,
            task_id=task_id,
            input_facts_hash=snapshot.hash,
            ruleset_hash=_RULESET_HASH,
            snapshot_hash=proposal.snapshot_hash,
            timeout_seconds=timeout_seconds,
            requested_by=proposal.change.actor or 'system',
        )
        self._append_proof_enrichments(run, context)
        return run

    def _append_proof_enrichments(
        self,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> None:
        audit = _audit_log(context)
        for result in validation.solver_results:
            adapter = result.get('adapter')
            if not isinstance(adapter, str) or not adapter.startswith('atp-'):
                continue
            proof_trace = tuple(
                step for step in result.get('proofTrace', ()) if isinstance(step, dict)
            )
            counterexample = result.get('counterexample')
            if not proof_trace and not isinstance(counterexample, dict):
                continue
            append_proof_enrichment_once(
                audit,
                event_for_proof_enrichment(
                    validation,
                    adapter=adapter,
                    proof_trace=proof_trace,
                    counterexample=counterexample if isinstance(counterexample, dict) else None,
                    session_id=_session_id(context),
                    actor=validation.requested_by,
                ),
            )

    def _emit_snapshot_metrics(self, context: 'ToolContext') -> None:
        """Emit counts derived from the current facts snapshot."""
        try:
            snapshot = self.snapshot(context)
        except Exception:  # pragma: no cover - metrics must never break validation
            return
        metrics.record_blocked_tasks(len(snapshot.blocked_ids))
        try:
            tms = get_logical_kanban(context).tms
            stale_count = tms.stale_assumption_count
        except Exception:
            stale_count = 0
        metrics.record_stale_assumptions(stale_count)

    def _do_validate(self, proposal: Proposal, context: 'ToolContext') -> ValidationRun:
        if proposal.change.kind == 'create_task':
            task_id = proposal.change.payload.get('taskId')
            return self._accepted(
                proposal,
                task_id=task_id if isinstance(task_id, str) else None,
                derived_facts=(
                    f'Task({task_id})',
                    f'Pending({task_id})',
                    f'Status({task_id}, pending)',
                ),
                proof_trace=(
                    {
                        'rule': 'LKB-CREATE-001',
                        'premises': ['CreateTaskProposal'],
                        'conclusion': 'Create structural task facts.',
                        'solverVersion': self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == 'propose_assertion':
            return self._validate_propose_assertion(proposal, context)
        if proposal.change.kind == 'legacy_todo_replace_all':
            return self._validate_legacy_todo_replace_all(proposal, context)
        if proposal.change.kind == 'transition_status':
            return self._validate_status_transition(proposal, context)
        if proposal.change.kind in {
            'update_task_fields',
            'delete_task',
            'add_dependency',
            'remove_dependency',
        }:
            return self._validate_structural_task_change(proposal, context)
        return self._accepted(proposal)

    def commit(
        self,
        proposal: Proposal,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> CommitResult:
        accepted = validation.accepted
        if accepted and proposal.change.kind == 'transition_status':
            accepted = self._validation_is_fresh(validation, context)
        if accepted:
            commit = CommitResult(
                committed=True,
                proposal_id=proposal.proposal_id,
                validation_run_id=validation.validation_run_id,
                derived_facts=validation.derived_facts,
            )
        else:
            reason_code = validation.issues[0].code if validation.issues else 'validation_denied'
            if proposal.change.kind == 'transition_status' and not self._validation_is_fresh(validation, context):
                reason_code = 'validation_stale'
            commit = CommitResult(
                committed=False,
                proposal_id=proposal.proposal_id,
                validation_run_id=validation.validation_run_id,
                reason={
                    'code': reason_code,
                    'validation': validation.to_dict(),
                },
            )
        _audit_log(context).append(
            event_for_commit(proposal, validation, commit, session_id=_session_id(context))
        )
        if not commit.committed and validation.issues:
            metrics.record_denial(
                rule=validation.issues[0].rule,
                code=validation.issues[0].code,
                change_kind=proposal.change.kind,
                task_id=validation.task_id,
                validation_run_id=validation.validation_run_id,
            )
        metrics.record_commit(
            committed=commit.committed,
            change_kind=proposal.change.kind,
            task_id=validation.task_id,
            validation_run_id=validation.validation_run_id,
        )
        if commit.committed:
            self._persist_accepted_metadata(proposal, validation, context)
        return commit

    def _validation_is_fresh(
        self,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> bool:
        """Return True when the validation run matches the current snapshot.

        F-139 requires that a status-transition commit is backed by a current
        validation run.  We compare the run's input_facts_hash to the current
        snapshot hash; any drift between propose/validate and commit denies the
        commit and forces revalidation.
        """
        if not validation.input_facts_hash:
            return False
        try:
            current_snapshot = self.snapshot(context)
        except Exception:  # pragma: no cover - defensive only
            return False
        return validation.input_facts_hash == current_snapshot.hash

    def _persist_accepted_metadata(
        self,
        proposal: Proposal,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> None:
        """Store validation-run metadata in the affected task's metadata.lkb."""
        task_id = validation.task_id
        if task_id is None:
            payload = proposal.change.payload
            if isinstance(payload, dict):
                task_id = payload.get('taskId') if isinstance(payload.get('taskId'), str) else None
        if task_id is None:
            return
        tasks = getattr(context, 'tasks', None)
        if not isinstance(tasks, dict):
            return
        task = tasks.get(task_id)
        if not isinstance(task, dict):
            return
        metadata = dict(task.get('metadata') or {})
        lkb = dict(metadata.get('lkb') or {})
        lkb['validation_run_id'] = validation.validation_run_id
        lkb['proposal_id'] = proposal.proposal_id
        lkb['last_decision'] = 'committed'
        lkb['last_result'] = validation.result
        lkb['validated_at'] = validation.created_at
        lkb['proof_trace'] = list(validation.proof_trace)
        metadata['lkb'] = lkb
        task['metadata'] = metadata

    # ------------------------------------------------------------------
    # F-141 Causal Verification Layer
    # ------------------------------------------------------------------

    def _apply_causal_gate(
        self,
        proposal: Proposal,
        snapshot: FactsSnapshot,
        validation: ValidationRun,
        *,
        edges: tuple[tuple[str, str], ...] = (),
        context: 'ToolContext',
    ) -> ValidationRun:
        """Run the F-141 causal gate after the symbolic gate has passed.

        ``edges`` is the set of (treatment, outcome) pairs whose causal
        weight should be evaluated.  When the feature is disabled, the
        input ``validation`` is returned unchanged.

        The gate is advisory by default; a ``weak`` outcome only becomes
        a binding denial when ``LKB_STRICT_CAUSAL`` is set in the
        environment (or via the stricter ``strict_causal`` override on
        the runtime).  The conservative aggregation from F-138 still
        wins: a symbolic fail never reaches this method.

        The output ``ValidationRun`` always carries a ``causal`` sub-record
        in ``counterexample`` when the gate produced new information.
        When the original ``counterexample`` was ``None`` (because the
        symbolic gate passed cleanly), the new ``counterexample`` is
        ``{"causal": {…}}`` so consumers always know the gate ran.
        """
        if not is_causal_verification_enabled() or not edges:
            return validation
        if validation.result != 'pass':
            # Defensive: a non-pass validation should not reach this gate.
            return validation
        graph = build_causal_graph(snapshot)
        if not graph.edges:
            return validation
        evaluated: list[CausalEffect] = []
        for treatment, outcome in edges:
            effect = self.causal_engine.intervene_do(
                graph,
                treatment_node=treatment,
                treatment_value='completed',
                outcome_node=outcome,
            )
            evaluated.append(effect)
        if not evaluated:
            return validation
        worst = min(
            evaluated,
            key=lambda effect: (
                0 if effect.tag == 'significant' else 1 if effect.tag == 'moderate' else 2,
            ),
        )

        causal_record: dict[str, Any] = {
            'engine': 'lkb-f141-causal',
            'engineVersion': 'f141-v1',
            'gate': 'advisory' if not is_strict_causal_enabled() else 'strict',
            'graphSnapshotHash': graph.snapshot_hash,
            'edges': [
                {'source': s, 'target': t}
                for s, t in edges
            ],
            'evaluations': [effect.to_dict() for effect in evaluated],
            'worst': {
                'tag': worst.tag,
                'weight': worst.weight,
                'mechanism': worst.mechanism,
                'isSignificant': worst.is_significant,
                'edge': {'source': worst.source, 'target': worst.target},
            },
        }

        existing_counterexample = validation.counterexample or {}
        if not existing_counterexample:
            new_counterexample: dict[str, Any] = {'causal': causal_record}
        else:
            new_counterexample = {**existing_counterexample, 'causal': causal_record}
        annotated = replace(validation, counterexample=new_counterexample)

        if worst.tag == 'weak' and is_strict_causal_enabled():
            issue = ValidationIssue(
                code='causal_weight_weak',
                message=(
                    f'Causal effect on edge {worst.source}->{worst.target} '
                    f'is weak (weight={worst.weight}); strict mode denies the change.'
                ),
                rule='LKB-CAUSAL-001',
                task_id=validation.task_id,
                repair_suggestions=(
                    RepairSuggestion(
                        action='clarify_ambiguity',
                        target=worst.source,
                        message=(
                            'Provide a manual cause declaration via '
                            'metadata.lkb.causes with weight >= 0.7, or '
                            'invoke override_causal with a justification.'
                        ),
                    ),
                ),
            )
            metrics.record_denial(
                rule='LKB-CAUSAL-001',
                code='causal_weight_weak',
                change_kind=proposal.change.kind,
                task_id=validation.task_id,
                validation_run_id=validation.validation_run_id,
            )
            return replace(
                annotated,
                result='fail',
                issues=(issue,),
                proof_trace=(
                    *annotated.proof_trace,
                    {
                        'rule': 'LKB-CAUSAL-001',
                        'premises': [worst.source, worst.target],
                        'conclusion': (
                            f'CausalWeight({worst.source}->{worst.target})={worst.weight}'
                        ),
                        'solverVersion': 'f141-v1',
                    },
                ),
            )
        return annotated

    def override_causal(
        self,
        *,
        edge: tuple[str, str],
        reason: str,
        weight: float,
        approver: str,
        validation_run_id: str | None = None,
        proposal_id: str | None = None,
        context: 'ToolContext',
    ) -> AuditEvent:
        """Record a human override of a ``weak`` causal outcome.

        Emits an ``lkb_human_override`` audit event with the canonical
        F-141 fields (``proposal_id``, ``edge``, ``justification``,
        ``approver``) and attaches ``metadata.lkb.causal_override`` to
        the source task so downstream tools can see who accepted the
        weak edge.
        """
        source, target = edge
        sanitised_weight = round(
            max(0.0, min(1.0, float(weight) if isinstance(weight, (int, float)) and not isinstance(weight, bool) else 0.0)),
            3,
        )
        previous = event_for_human_override(
            assumption_id=f'causal:{source}->{target}',
            assertion_id=validation_run_id or f'edge:{source}->{target}',
            actor=approver,
            reason=reason,
            previous_result='weak',
            task_ids=(source, target),
            validation_run_id=validation_run_id,
            session_id=_session_id(context),
        )
        # Rebuild the event so the payload exposes the F-141 field names
        # (``proposal_id``, ``edge``, ``justification``, ``approver``).
        event = AuditEvent(
            event_id=previous.event_id,
            event_type=previous.event_type,
            actor=previous.actor,
            timestamp=previous.timestamp,
            session_id=previous.session_id,
            proposal_id=proposal_id,
            validation_run_id=validation_run_id,
            task_id=source,
            decision=previous.decision,
            payload={
                'overrideType': 'causal',
                'proposal_id': proposal_id,
                'edge': {'source': source, 'target': target},
                'justification': reason,
                'approver': approver,
                'weight': sanitised_weight,
                'previousResult': 'weak',
                'assumptionId': previous.payload.get('assumptionId'),
                'assertionId': previous.payload.get('assertionId'),
            },
        )
        _audit_log(context).append(event)
        self._attach_causal_override_metadata(
            context,
            source=source,
            target=target,
            approver=approver,
            reason=reason,
            weight=sanitised_weight,
        )
        return event

    def _attach_causal_override_metadata(
        self,
        context: 'ToolContext',
        *,
        source: str,
        target: str,
        approver: str,
        reason: str,
        weight: float,
    ) -> None:
        """Write ``metadata.lkb.causal_override`` on the source task."""
        tasks = getattr(context, 'tasks', None)
        if not isinstance(tasks, dict):
            return
        task = tasks.get(source)
        if not isinstance(task, dict):
            return
        metadata = dict(task.get('metadata') or {})
        lkb = dict(metadata.get('lkb') or {})
        lkb['causal_override'] = {
            'source': source,
            'target': target,
            'approver': approver,
            'reason': reason,
            'weight': weight,
            'overriddenAt': datetime.now(timezone.utc).isoformat(),
        }
        metadata['lkb'] = lkb
        task['metadata'] = metadata

    def _apply_causal_gate_for_transition(
        self,
        proposal: Proposal,
        snapshot: FactsSnapshot,
        task_id: str,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> ValidationRun:
        """Run the F-141 causal gate for a status transition.

        The affected edges are the upstream blockers of ``task_id`` —
        each ``(blocker, task_id)`` pair is the causal claim that
        completing the blocker will enable the target.  When the task has
        no upstream blockers the gate is skipped (there is nothing
        causally to evaluate).
        """
        if not is_causal_verification_enabled():
            return validation
        blockers = sorted(set(snapshot.blocked_by.get(task_id, ())))
        if not blockers:
            return validation
        edges = tuple((blocker, task_id) for blocker in blockers)
        return self._apply_causal_gate(
            proposal,
            snapshot,
            validation,
            edges=edges,
            context=context,
        )

    def _apply_causal_gate_for_dependency(
        self,
        proposal: Proposal,
        snapshot: FactsSnapshot,
        payload: dict[str, Any],
        task_id: str | None,
        validation: ValidationRun,
        context: 'ToolContext',
    ) -> ValidationRun:
        """Run the F-141 causal gate for an ``add_dependency`` change.

        The affected edges are the *new* edges being added by the
        proposal (``addBlockedBy`` for the target, or ``addBlocks`` for
        the inverse direction).  Existing edges are skipped — the
        symbolic gate already vouched for their cycle-freeness, and the
        causal gate only needs to score the *new* mechanistic claim.
        """
        if not is_causal_verification_enabled():
            return validation
        if not isinstance(task_id, str):
            return validation
        edges: list[tuple[str, str]] = []
        for blocker in _string_list(payload.get('addBlockedBy')):
            if blocker == task_id:
                continue
            edges.append((blocker, task_id))
        for dependent in _string_list(payload.get('addBlocks')):
            if dependent == task_id:
                continue
            edges.append((task_id, dependent))
        if not edges:
            return validation
        return self._apply_causal_gate(
            proposal,
            snapshot,
            validation,
            edges=tuple(edges),
            context=context,
        )

    def run(
        self,
        change: ProposedChange,
        context: 'ToolContext',
    ) -> tuple[Proposal, ValidationRun, CommitResult]:
        proposal = self.propose(change, context)
        validation = self.validate(proposal, context)
        commit = self.commit(proposal, validation, context)
        return proposal, validation, commit

    def evaluate_assertion(
        self,
        text: str,
        base_assertion: 'CanonicalAssertion',
        *,
        assertion_id: str | None = None,
        context_facts: tuple[str, ...] = (),
        context: 'ToolContext | None' = None,
    ) -> MultiWorldResult:
        """Detect ambiguities in ``text`` and generate possible worlds.

        This is the entry point for the F-134 fuzzy input layer.  It runs the
        symbol-based ambiguity detector, builds one CanonicalAssertion per
        consistent interpretation, and returns a MultiWorldResult.
        """
        from .ir import CanonicalAssertion

        assertion_id = assertion_id or _new_id('A-')
        if not isinstance(base_assertion, CanonicalAssertion):
            raise TypeError('base_assertion must be a CanonicalAssertion')
        audit_log = _audit_log(context) if context is not None else None
        detector = AmbiguityDetector(
            library=self._pattern_library, audit_log=audit_log,
        )
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
        context: 'ToolContext',
        *,
        target_task_id: str | None = None,
        target_status: str | None = None,
        is_irreversible: bool = True,
    ) -> tuple[AggregationDecision, CommitDecision]:
        """Validate every world and decide whether the assertion may commit.

        Returns the aggregation decision and the final fuzzy commit decision.
        """
        snapshot = self._augmented_snapshot(context)
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
        context: 'ToolContext',
    ) -> ValidationRun:
        """Validate a natural-language assertion proposal through the fuzzy layer."""
        from .ir import CanonicalAssertion

        payload = proposal.change.payload
        text = payload.get('text') if isinstance(payload, dict) else ''
        base_assertion = payload.get('baseAssertion')
        target_task_id = payload.get('targetTaskId')
        target_status = payload.get('targetStatus')

        if not isinstance(text, str) or not text:
            issue = ValidationIssue(
                code='missing_assertion_text',
                message='Assertion proposal must include a non-empty text field.',
                rule='LKB-ASSERTION-001',
            )
            return self._denied(proposal, issues=(issue,))

        if not isinstance(base_assertion, CanonicalAssertion):
            issue = ValidationIssue(
                code='missing_base_assertion',
                message='Assertion proposal must include a base CanonicalAssertion.',
                rule='LKB-ASSERTION-002',
            )
            return self._denied(proposal, issues=(issue,))

        multi_world = self.evaluate_assertion(
            text,
            base_assertion,
            assertion_id=payload.get('assertionId'),
            context_facts=tuple(payload.get('contextFacts', [])),
            context=context,
        )
        aggregation, commit_decision = self.validate_assertion_proposal(
            multi_world,
            context,
            target_task_id=target_task_id if isinstance(target_task_id, str) else None,
            target_status=target_status if isinstance(target_status, str) else None,
            is_irreversible=bool(payload.get('isIrreversible', True)),
        )

        if not commit_decision.commit:
            issue = ValidationIssue(
                code=commit_decision.reason,
                message=commit_decision.human_message.get(
                    'en', 'Fuzzy commit gate denied the assertion.'
                ),
                rule='LKB-FUZZY-COMMIT-001',
                task_id=target_task_id if isinstance(target_task_id, str) else None,
                repair_suggestions=tuple(
                    RepairSuggestion(
                        action='clarify_ambiguity',
                        target=a.assumption_id,
                        message=a.clarification_prompt,
                    )
                    for w in multi_world.worlds
                    for a in w.assumptions
                    if a.needs_clarification
                ),
            )
            derived_facts = tuple(
                f'Assumes({a.assertion_id}, {a.assumption_id}, {a.assumed_value})'
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
                        'rule': 'LKB-FUZZY-COMMIT-001',
                        'premises': [
                            a.assumption_id for w in multi_world.worlds for a in w.assumptions
                        ],
                        'conclusion': f'FuzzyCommitDecision({commit_decision.reason})',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        derived_facts = tuple(
            f'Assumes({a.assertion_id}, {a.assumption_id}, {a.assumed_value})'
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
                    'rule': 'LKB-FUZZY-COMMIT-ALLOW',
                    'premises': [w.world_id for w in multi_world.worlds],
                    'conclusion': f'Aggregation({aggregation.strategy})',
                    'solverVersion': self.solver_version,
                },
            ),
        )

    def _validate_legacy_todo_replace_all(
        self,
        proposal: Proposal,
        context: 'ToolContext',
    ) -> ValidationRun:
        todos = proposal.change.payload.get('todos')
        if not isinstance(todos, list):
            issue = ValidationIssue(
                code='malformed_legacy_todo_write',
                message='TodoWrite payload must contain a todos array.',
                rule='LKB-TODOWRITE-COMPAT-001',
            )
            return self._denied(
                proposal,
                issues=(issue,),
                proof_trace=(
                    {
                        'rule': 'LKB-TODOWRITE-COMPAT-001',
                        'premises': ['Not(Array(todos))'],
                        'conclusion': 'DenyCommit',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        status_counts = {'pending': 0, 'in_progress': 0, 'completed': 0}
        malformed_indexes: list[int] = []
        in_progress_ids: list[str] = []
        derived_facts: list[str] = []
        for index, todo in enumerate(todos):
            todo_id = f'todo:{index}'
            if not isinstance(todo, dict) or todo.get('status') not in status_counts:
                malformed_indexes.append(index)
                continue
            status = str(todo['status'])
            status_counts[status] += 1
            if status == 'in_progress':
                in_progress_ids.append(todo_id)
            derived_facts.extend((f'Task({todo_id})', f'Status({todo_id}, {status})'))

        if malformed_indexes:
            issue = ValidationIssue(
                code='malformed_legacy_todo_write',
                message=(
                    'TodoWrite contains malformed todos at indexes: '
                    f'{", ".join(str(i) for i in malformed_indexes)}.'
                ),
                rule='LKB-TODOWRITE-COMPAT-001',
                blockers=tuple(f'todo:{i}' for i in malformed_indexes),
            )
            return self._denied(
                proposal,
                issues=(issue,),
                proof_trace=(
                    {
                        'rule': 'LKB-TODOWRITE-COMPAT-001',
                        'premises': [f'Malformed(todo:{i})' for i in malformed_indexes],
                        'conclusion': 'DenyCommit',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        total = len(todos)
        derived_facts.append(
            'TodoProgress('
            f'total={total}, '
            f'pending={status_counts["pending"]}, '
            f'in_progress={status_counts["in_progress"]}, '
            f'completed={status_counts["completed"]}'
            ')'
        )
        if total > 0 and status_counts['completed'] == total:
            derived_facts.append('AllLegacyTodosCompleted')

        runtime = getattr(context, 'logical_kanban', None)
        if (
            bool(getattr(runtime, 'strict_logical_todo_enabled', False))
            and len(in_progress_ids) > 1
        ):
            issue = ValidationIssue(
                code='multiple_in_progress_legacy_todo_write',
                message=(
                    'TodoWrite cannot set multiple in_progress todos while strict '
                    f'logical todo mode is enabled: {", ".join(in_progress_ids)}.'
                ),
                rule='LKB-TODOWRITE-COMPAT-002',
                blockers=tuple(in_progress_ids),
                repair_suggestions=(
                    RepairSuggestion(
                        action='keep_single_in_progress',
                        target=in_progress_ids[0],
                        message='Leave only one todo in_progress and keep the others pending.',
                    ),
                ),
            )
            return self._denied(
                proposal,
                issues=(issue,),
                derived_facts=tuple(derived_facts),
                proof_trace=(
                    {
                        'rule': 'LKB-TODOWRITE-COMPAT-002',
                        'premises': [f'Doing({todo_id})' for todo_id in in_progress_ids],
                        'conclusion': 'DenyCommit',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        # F-144: run the fuzzy gate over legacy todo content when LKB is enabled.
        if is_logical_kanban_enabled():
            audit_log = _audit_log(context)
            detector = AmbiguityDetector(
                library=self._pattern_library, audit_log=audit_log,
            )
            ambiguous_todos: list[tuple[str, AmbiguityReport]] = []
            ambiguity_derived_facts: list[str] = []
            for index, todo in enumerate(todos):
                todo_id = f'todo:{index}'
                content = todo.get('content') if isinstance(todo, dict) else None
                if isinstance(content, str) and content.strip():
                    report = detector.detect(
                        content,
                        assertion_id=todo_id,
                        context_facts=tuple(derived_facts),
                    )
                    ambiguity_derived_facts.append(
                        f'AmbiguityDetected({todo_id}, {report.severity}, '
                        f'{len(report.detected_ambiguities)})'
                    )
                    if report.severity in {'critical', 'major'} and report.needs_clarification:
                        ambiguous_todos.append((todo_id, report))

            if ambiguous_todos:
                combined_ambiguities = tuple(
                    amb
                    for _todo_id, report in ambiguous_todos
                    for amb in report.detected_ambiguities
                )
                combined_report = AmbiguityReport(
                    assertion_id=proposal.proposal_id,
                    detected_ambiguities=combined_ambiguities,
                    severity=max(
                        (report.severity for _todo_id, report in ambiguous_todos),
                        key=_severity_rank,
                    ),
                    needs_clarification=True,
                )

                from .ir import make_canonical, pred

                base_assertion = make_canonical(
                    role='assumption',
                    kind='consistency',
                    body=pred('LegacyTodoBatch', proposal.proposal_id),
                )
                worlds = WorldGenerator().generate(combined_report, base_assertion)
                validator = MultiWorldValidator(self.engine)
                world_results = validator.validate(
                    worlds, self._augmented_snapshot(context)
                )
                commit_decision = commit_gate_fuzzy_check(
                    worlds,
                    world_results,
                    combined_report,
                    is_irreversible=False,
                )

                # Any critical/major ambiguity is enough to deny the batch.
                if not commit_decision.commit or combined_report.severity in {'critical', 'major'}:
                    legacy_ambiguities = tuple(
                        _legacy_todo_ambiguity_dict(todo_id, report)
                        for todo_id, report in ambiguous_todos
                    )
                    repair_suggestions = tuple(
                        RepairSuggestion(
                            action='clarify_ambiguity',
                            target=entry['todoId'],
                            message=entry['clarificationPrompt'],
                        )
                        for entry in legacy_ambiguities
                    )
                    issue = ValidationIssue(
                        code='LKB-TODOWRITE-AMBIG-001',
                        message=_legacy_todo_denial_message(legacy_ambiguities, commit_decision),
                        rule='LKB-TODOWRITE-AMBIG-001',
                        repair_suggestions=repair_suggestions,
                    )
                    ambiguity_derived_facts.extend(
                        f'Assumes({a.assertion_id}, {a.assumption_id}, {a.assumed_value})'
                        for w in worlds
                        for a in w.assumptions
                    )
                    validation = self._denied(
                        proposal,
                        issues=(issue,),
                        derived_facts=tuple(derived_facts) + tuple(ambiguity_derived_facts),
                        proof_trace=(
                            {
                                'rule': 'LKB-TODOWRITE-AMBIG-001',
                                'premises': [
                                    f'Ambiguity({entry["todoId"]}, {entry["severity"]}, {entry["ambiguityCode"]})'
                                    for entry in legacy_ambiguities
                                ],
                                'conclusion': 'DenyCommit',
                                'solverVersion': self.solver_version,
                            },
                        ),
                        legacy_todo_ambiguities=legacy_ambiguities,
                    )
                    session_id = _session_id(context)
                    for entry in legacy_ambiguities:
                        audit_log.append(
                            event_for_legacy_todo_ambiguity(
                                entry['todoId'],
                                entry['ambiguityCode'],
                                entry['severity'],
                                entry['clarificationPrompt'],
                                validation_run_id=validation.validation_run_id,
                                session_id=session_id,
                            )
                        )
                    return validation

        return self._accepted(
            proposal,
            derived_facts=tuple(derived_facts),
            proof_trace=(
                {
                    'rule': 'LKB-TODOWRITE-COMPAT-ALLOW',
                    'premises': [
                        'LegacyTodoWriteCompatibilityMode',
                        f'InProgressCount({status_counts["in_progress"]})',
                    ],
                    'conclusion': 'Allow legacy TodoWrite replacement.',
                    'solverVersion': self.solver_version,
                },
            ),
        )

    def _validate_status_transition(
        self,
        proposal: Proposal,
        context: 'ToolContext',
    ) -> ValidationRun:
        payload = proposal.change.payload
        task_id = payload.get('taskId')
        target_status = payload.get('status')
        if not isinstance(task_id, str) or target_status not in {
            'pending',
            'in_progress',
            'completed',
        }:
            return self._accepted(proposal)

        # F-135: a task whose readiness depends on a stale derived fact must
        # not be allowed to commit a status transition.
        stale_check = self._check_stale_assumption_for_task(context, task_id)
        if stale_check is not None:
            return stale_check

        task = (getattr(context, 'tasks', {}) or {}).get(task_id)
        if not isinstance(task, dict):
            issue = ValidationIssue(
                code='task_not_found',
                message=f'Task {task_id} does not exist.',
                rule='LKB-TRANSITION-001',
                task_id=task_id,
            )
            return self._denied(
                proposal,
                task_id=task_id,
                issues=(issue,),
                proof_trace=(
                    {
                        'rule': 'LKB-TRANSITION-001',
                        'premises': [f'Not(Task({task_id}))'],
                        'conclusion': f'Not(CanMoveTo({task_id}, {target_status}))',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        current_status = task.get('status')
        snapshot = self._augmented_snapshot(context)
        if current_status == target_status:
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=(f'NoStatusChange({task_id})',),
                proof_trace=(
                    {
                        'rule': 'LKB-NOOP-001',
                        'premises': [f'Status({task_id}, {target_status})'],
                        'conclusion': f'NoStatusChange({task_id})',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        if target_status == 'pending' and current_status == 'completed':
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=(f'Reopened({task_id})',),
                proof_trace=(
                    {
                        'rule': 'LKB-REOPEN-001',
                        'premises': [f'Status({task_id}, completed)', 'ExplicitReopen'],
                        'conclusion': f'CanMoveTo({task_id}, pending)',
                        'solverVersion': self.solver_version,
                    },
                ),
            )

        if target_status == 'completed':
            pipeline_result = self._run_transition_pipeline(
                proposal, snapshot, task_id, target_status, context, task, payload
            )
            if pipeline_result.result != 'pass':
                issues = self._transition_issues_from_pipeline_result(
                    pipeline_result, task_id, snapshot
                )
                return self._denied(
                    proposal,
                    task_id=task_id,
                    issues=issues,
                    snapshot=snapshot,
                    derived_facts=pipeline_result.derived_facts,
                    proof_trace=pipeline_result.proof_trace,
                    engine=pipeline_result.engine,
                    engine_version=pipeline_result.engine_version,
                    solver_results=pipeline_result.solver_results,
                    result=pipeline_result.result,
                )
            accepted = self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=pipeline_result.derived_facts,
                proof_trace=pipeline_result.proof_trace,
                engine=pipeline_result.engine,
                engine_version=pipeline_result.engine_version,
                solver_results=pipeline_result.solver_results,
            )
            return self._apply_causal_gate_for_transition(
                proposal, snapshot, task_id, accepted, context
            )

        if target_status == 'in_progress':
            pipeline_result = self._run_transition_pipeline(
                proposal, snapshot, task_id, target_status, context, task, payload
            )
            if pipeline_result.result != 'pass':
                issues = self._transition_issues_from_pipeline_result(
                    pipeline_result, task_id, snapshot
                )
                return self._denied(
                    proposal,
                    task_id=task_id,
                    issues=issues,
                    snapshot=snapshot,
                    derived_facts=pipeline_result.derived_facts,
                    proof_trace=pipeline_result.proof_trace,
                    engine=pipeline_result.engine,
                    engine_version=pipeline_result.engine_version,
                    solver_results=pipeline_result.solver_results,
                    result=pipeline_result.result,
                )
            accepted = self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=pipeline_result.derived_facts,
                proof_trace=pipeline_result.proof_trace,
                engine=pipeline_result.engine,
                engine_version=pipeline_result.engine_version,
                solver_results=pipeline_result.solver_results,
            )
            return self._apply_causal_gate_for_transition(
                proposal, snapshot, task_id, accepted, context
            )

        return self._accepted(
            proposal,
            task_id=task_id,
            derived_facts=(f'CanMoveTo({task_id}, {target_status})',),
        )

    def _run_transition_pipeline(
        self,
        proposal: Proposal,
        snapshot: FactsSnapshot,
        task_id: str,
        target_status: str,
        context: 'ToolContext',
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> ValidationRun:
        """Run the solver pipeline for a status transition."""
        request = SolverRequest(
            snapshot=snapshot,
            target_task_id=task_id,
            target_status=target_status,
            strict_acceptance=(
                self._strict_acceptance_enabled(context, task, payload)
                if target_status == 'completed'
                else False
            ),
            acceptance_proof_present=(
                self._has_acceptance_proof(task, payload)
                if target_status == 'completed'
                else None
            ),
        )
        return self.pipeline.validate(
            request,
            proposal_id=proposal.proposal_id,
            task_id=task_id,
            input_facts_hash=snapshot.hash,
            ruleset_hash=_RULESET_HASH,
            snapshot_hash=proposal.snapshot_hash,
            requested_by=proposal.change.actor or 'system',
        )

    def _transition_issues_from_pipeline_result(
        self,
        pipeline_result: ValidationRun,
        task_id: str,
        snapshot: FactsSnapshot,
    ) -> tuple[ValidationIssue, ...]:
        """Build human-readable issues from the pipeline's aggregate result."""
        if pipeline_result.result in ('unknown', 'timeout', 'error'):
            return (
                ValidationIssue(
                    code=f'solver_{pipeline_result.result}',
                    message=(
                        f'Solver pipeline returned {pipeline_result.result} for task '
                        f'{task_id}; the transition cannot be committed safely.'
                    ),
                    rule='LKB-SOLVER-AGG-001',
                    task_id=task_id,
                    repair_suggestions=(
                        RepairSuggestion(
                            action='revalidate_task',
                            target=task_id,
                            message='Retry the transition once the solver is available.',
                            priority=1,
                        ),
                    ),
                ),
            )

        layer1 = next(
            (
                r
                for r in pipeline_result.solver_results
                if r.get('adapter') == 'layer1-python'
            ),
            None,
        )
        if layer1 is None:
            return (
                ValidationIssue(
                    code='solver_fail_no_layer1',
                    message='Solver pipeline failed but no Layer-1 response is available.',
                    rule='LKB-SOLVER-AGG-002',
                    task_id=task_id,
                ),
            )

        violated_rule = layer1.get('violatedRule')
        message = layer1.get('message', '')
        cycle_tasks = tuple(layer1.get('cycleTasks', []))

        if violated_rule == 'R-006':
            issue = ValidationIssue(
                code='cyclic_dependency_blocks_readiness',
                message=message,
                rule=violated_rule,
                task_id=task_id,
                blockers=cycle_tasks,
                repair_suggestions=(
                    RepairSuggestion(
                        action='fix_cycle',
                        target=task_id,
                        message='Remove or rewrite one dependency edge in the cycle.',
                        priority=1,
                    ),
                    RepairSuggestion(
                        action='remove_dependency',
                        target=task_id,
                        message='Remove one reciprocal or transitive dependency edge.',
                        priority=2,
                    ),
                    RepairSuggestion(
                        action='split_task',
                        target=task_id,
                        message='Consider splitting the task to break the cycle.',
                        priority=3,
                    ),
                ),
            )
        elif violated_rule == 'R-005':
            issue = ValidationIssue(
                code='completed_requires_acceptance_proof',
                message=message,
                rule=violated_rule or 'R-005',
                task_id=task_id,
                repair_suggestions=(
                    RepairSuggestion(
                        action='add_acceptance_proof',
                        target=task_id,
                        message='Attach metadata.lkb.acceptance_proof before completing the task.',
                        priority=1,
                    ),
                    RepairSuggestion(
                        action='revalidate_task',
                        target=task_id,
                        message='Keep the task in_progress until acceptance proof is available.',
                        priority=2,
                    ),
                ),
            )
        else:
            blockers = list(active_blockers(snapshot, task_id))
            suggestions: list[RepairSuggestion] = [
                RepairSuggestion(
                    action='complete_prerequisite',
                    target=blocker,
                    message=f'Complete blocker {blocker} before starting {task_id}.',
                    priority=1,
                )
                for blocker in blockers
            ]
            suggestions.append(
                RepairSuggestion(
                    action='remove_dependency',
                    target=task_id,
                    message='Remove the dependency if it is no longer required.',
                    priority=2,
                ),
            )
            if len(blockers) > 1:
                suggestions.append(
                    RepairSuggestion(
                        action='split_task',
                        target=task_id,
                        message='Consider splitting the task into smaller pieces.',
                        priority=3,
                    ),
                )
            issue = ValidationIssue(
                code='blocked_task_cannot_enter_in_progress',
                message=message,
                rule=violated_rule or 'R-002',
                task_id=task_id,
                blockers=tuple(blockers),
                repair_suggestions=tuple(suggestions),
            )
        return (issue, *snapshot.warnings)

    def _validate_structural_task_change(
        self,
        proposal: Proposal,
        context: 'ToolContext',
    ) -> ValidationRun:
        payload = proposal.change.payload
        task_id = payload.get('taskId')
        if isinstance(task_id, str) and task_id not in (getattr(context, 'tasks', {}) or {}):
            issue = ValidationIssue(
                code='task_not_found',
                message=f'Task {task_id} does not exist.',
                rule='LKB-STRUCTURE-001',
                task_id=task_id,
            )
            return self._denied(
                proposal,
                task_id=task_id,
                issues=(issue,),
                proof_trace=(
                    {
                        'rule': 'LKB-STRUCTURE-001',
                        'premises': [f'Not(Task({task_id}))'],
                        'conclusion': 'DenyCommit',
                        'solverVersion': self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == 'delete_task':
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=(f'CanDelete({task_id})', 'CascadeDependencyCleanupAfterValidation'),
                proof_trace=(
                    {
                        'rule': 'LKB-DELETE-001',
                        'premises': [f'Task({task_id})'],
                        'conclusion': f'CanDelete({task_id})',
                        'solverVersion': self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == 'update_task_fields':
            return self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=(f'CanUpdateTaskFields({task_id})',),
                proof_trace=(
                    {
                        'rule': 'LKB-FIELDS-001',
                        'premises': [f'Task({task_id})'],
                        'conclusion': f'CanUpdateTaskFields({task_id})',
                        'solverVersion': self.solver_version,
                    },
                ),
            )
        if proposal.change.kind == 'add_dependency':
            preview = self._preview_dependency_context(context, payload)
            snapshot = self._augmented_snapshot(preview)  # type: ignore[arg-type]
            task_cycle = (
                sorted(snapshot.cycle_task_ids)
                if not isinstance(task_id, str)
                else sorted(
                    {task_id, *dependency_closure(snapshot, task_id)} & snapshot.cycle_task_ids
                )
            )
            if task_cycle:
                issue = ValidationIssue(
                    code='dependency_cycle_denied',
                    message=(
                        'Dependency update would create a cycle involving: '
                        f'{", ".join(task_cycle)}.'
                    ),
                    rule='LKB-DEPENDENCY-002',
                    task_id=task_id if isinstance(task_id, str) else None,
                    blockers=tuple(task_cycle),
                    repair_suggestions=(
                        RepairSuggestion(
                            action='fix_cycle',
                            target=task_id if isinstance(task_id, str) else None,
                            message='Remove one reciprocal or transitive dependency edge.',
                            priority=1,
                        ),
                        RepairSuggestion(
                            action='remove_dependency',
                            target=task_id if isinstance(task_id, str) else None,
                            message='Remove one dependency edge to break the cycle.',
                            priority=2,
                        ),
                        RepairSuggestion(
                            action='split_task',
                            target=task_id if isinstance(task_id, str) else None,
                            message='Consider splitting the task to break the cycle.',
                            priority=3,
                        ),
                    ),
                )
                return self._denied(
                    proposal,
                    task_id=task_id if isinstance(task_id, str) else None,
                    issues=(issue, *snapshot.warnings),
                    snapshot=snapshot,
                    derived_facts=tuple(f'Cycle({cycle_task_id})' for cycle_task_id in task_cycle),
                    proof_trace=(
                        {
                            'rule': 'LKB-DEPENDENCY-002',
                            'premises': [f'Cycle({cycle_task_id})' for cycle_task_id in task_cycle],
                            'conclusion': 'DenyCommit',
                            'solverVersion': self.solver_version,
                        },
                    ),
                )
            accepted = self._accepted(
                proposal,
                task_id=task_id,
                derived_facts=(f'CanMutateDependencies({task_id})',),
                proof_trace=(
                    {
                        'rule': 'LKB-DEPENDENCY-001',
                        'premises': [f'Task({task_id})', 'NoDependencyCycleAfterMutation'],
                        'conclusion': f'CanMutateDependencies({task_id})',
                        'solverVersion': self.solver_version,
                    },
                ),
            )
            return self._apply_causal_gate_for_dependency(
                proposal, snapshot, payload, task_id, accepted, context
            )
        return self._accepted(
            proposal,
            task_id=task_id,
            derived_facts=(f'CanMutateDependencies({task_id})',),
            proof_trace=(
                {
                    'rule': 'LKB-DEPENDENCY-001',
                    'premises': [f'Task({task_id})'],
                    'conclusion': f'CanMutateDependencies({task_id})',
                    'solverVersion': self.solver_version,
                },
            ),
        )

    def _preview_dependency_context(
        self,
        context: 'ToolContext',
        payload: dict[str, Any],
    ) -> Any:
        task_id = payload.get('taskId')
        tasks = {
            key: {
                **dict(value),
                'blocks': list((value or {}).get('blocks') or []),
                'blockedBy': list((value or {}).get('blockedBy') or []),
                'metadata': dict((value or {}).get('metadata') or {}),
            }
            for key, value in (getattr(context, 'tasks', {}) or {}).items()
            if isinstance(value, dict)
        }
        task = tasks.get(task_id) if isinstance(task_id, str) else None
        if task is not None:
            for rel_field, input_key in (('blocks', 'addBlocks'), ('blockedBy', 'addBlockedBy')):
                ids = payload.get(input_key)
                if isinstance(ids, list):
                    cur = list(task.get(rel_field) or [])
                    for item in ids:
                        if isinstance(item, str) and item not in cur:
                            cur.append(item)
                    task[rel_field] = cur
        return SimpleNamespace(tasks=tasks, todos=getattr(context, 'todos', ()))

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
        engine: str | None = None,
        engine_version: str | None = None,
        solver_results: tuple[dict[str, Any], ...] | None = None,
        legacy_todo_ambiguities: tuple[dict[str, Any], ...] = (),
    ) -> ValidationRun:
        if repair_suggestions is None:
            suggestions: list[RepairSuggestion] = []
            for issue in issues:
                if issue.repair_suggestions:
                    suggestions.extend(issue.repair_suggestions)
                else:
                    suggestions.extend(build_repair_suggestions(issue))
            repair_suggestions = tuple(suggestions)
        return ValidationRun(
            validation_run_id=_new_id('V-'),
            proposal_id=proposal.proposal_id,
            task_id=task_id,
            input_facts_hash=input_facts_hash or proposal.snapshot_hash,
            ruleset_hash=_RULESET_HASH,
            snapshot_hash=proposal.snapshot_hash,
            engine=engine or 'layer1-python',
            engine_version=engine_version if engine_version is not None else self.solver_version,
            result=result,
            derived_facts=derived_facts,
            proof_trace=proof_trace
            or (
                {
                    'rule': 'LKB-FOUNDATION-ALLOW',
                    'conclusion': 'No foundation rule denied this change.',
                    'solverVersion': self.solver_version,
                },
            ),
            counterexample=counterexample,
            repair_suggestions=repair_suggestions,
            issues=issues,
            created_at=datetime.now(timezone.utc).isoformat(),
            requested_by=proposal.change.actor or 'system',
            solver_results=solver_results or (),
            legacy_todo_ambiguities=legacy_todo_ambiguities,
        )

    def _counterexample_for(
        self,
        issue: ValidationIssue,
        snapshot: FactsSnapshot,
        task_id: str | None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            'violatedRule': issue.rule,
            'violatedPredicate': issue.code,
        }
        if task_id:
            out['taskId'] = task_id
        if issue.blockers:
            out['activeBlockers'] = list(issue.blockers)
        if task_id and task_id in snapshot.normalized_tasks:
            task = snapshot.normalized_tasks[task_id]
            out['model'] = {
                f'Status({task_id})': task['status'],
            }
            if issue.blockers:
                out['model'].update(
                    {
                        f'Status({blocker})': snapshot.normalized_tasks.get(blocker, {}).get(
                            'status'
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
        result: ValidationResult = 'fail',
        engine: str | None = None,
        engine_version: str | None = None,
        solver_results: tuple[dict[str, Any], ...] | None = None,
        legacy_todo_ambiguities: tuple[dict[str, Any], ...] = (),
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
            engine=engine,
            engine_version=engine_version,
            solver_results=solver_results,
            legacy_todo_ambiguities=legacy_todo_ambiguities,
        )

    def _accepted(
        self,
        proposal: Proposal,
        *,
        task_id: str | None = None,
        proof_trace: tuple[dict[str, Any], ...] | None = None,
        derived_facts: tuple[str, ...] = (),
        engine: str | None = None,
        engine_version: str | None = None,
        solver_results: tuple[dict[str, Any], ...] | None = None,
        legacy_todo_ambiguities: tuple[dict[str, Any], ...] = (),
    ) -> ValidationRun:
        return self._make_validation_run(
            proposal,
            result='pass',
            task_id=task_id,
            derived_facts=derived_facts,
            proof_trace=proof_trace,
            engine=engine,
            engine_version=engine_version,
            solver_results=solver_results,
            legacy_todo_ambiguities=legacy_todo_ambiguities,
        )

    def _strict_acceptance_enabled(
        self,
        context: 'ToolContext',
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        runtime = getattr(context, 'logical_kanban', None)
        if bool(getattr(runtime, 'strict_acceptance_enabled', False)):
            return True
        metadata = task.get('metadata') if isinstance(task.get('metadata'), dict) else {}
        lkb = metadata.get('lkb') if isinstance(metadata, dict) else {}
        if isinstance(lkb, dict) and bool(lkb.get('strict_acceptance')):
            return True
        incoming = payload.get('metadata')
        incoming_lkb = incoming.get('lkb') if isinstance(incoming, dict) else {}
        return isinstance(incoming_lkb, dict) and bool(incoming_lkb.get('strict_acceptance'))

    def _has_acceptance_proof(
        self,
        task: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        metadata = task.get('metadata') if isinstance(task.get('metadata'), dict) else {}
        lkb = metadata.get('lkb') if isinstance(metadata, dict) else {}
        if isinstance(lkb, dict) and bool(lkb.get('acceptance_proof')):
            return True
        incoming = payload.get('metadata')
        incoming_lkb = incoming.get('lkb') if isinstance(incoming, dict) else {}
        return isinstance(incoming_lkb, dict) and bool(incoming_lkb.get('acceptance_proof'))

    def _tms(self, context: 'ToolContext') -> TruthMaintenanceSystem:
        tms = get_logical_kanban(context).tms
        if tms.on_invalidate is None:
            session_id = _session_id(context)
            audit = _audit_log(context)

            def _on_invalidate(assumption_id: str, assertion_id: str, reason: str) -> None:
                assertion = tms.get_assertion(assertion_id)
                task_ids = tuple(assertion.task_ids) if assertion else ()
                audit.append(
                    event_for_assumption_invalidated(
                        assumption_id,
                        assertion_id,
                        reason=reason,
                        task_ids=task_ids,
                        session_id=session_id,
                    )
                )

            tms.on_invalidate = _on_invalidate
        return tms

    def _check_stale_assumption_for_task(
        self,
        context: 'ToolContext',
        task_id: str,
    ) -> ValidationRun | None:
        """Return a stale ValidationRun if task_id depends on a stale assertion."""
        tms = self._tms(context)
        if not tms.is_task_affected(task_id):
            return None
        stale_assertions = [
            assertion.assertion_id
            for assertion in tms.get_assertions_for_task(task_id)
            if assertion.status == 'stale'
        ]
        issue = ValidationIssue(
            code='stale_assumption_blocks_transition',
            message=(
                f'Task {task_id} cannot change status because one or more '
                'assumptions it depends on have been invalidated.'
            ),
            rule='LKB-TMS-001',
            task_id=task_id,
            repair_suggestions=(
                RepairSuggestion(
                    action='revalidate_task',
                    target=task_id,
                    message='Clarify or override the invalidated assumptions before transitioning.',
                    priority=1,
                ),
                RepairSuggestion(
                    action='clarify_ambiguity',
                    target=task_id,
                    message='Provide clarification for the invalidated assumptions.',
                    priority=2,
                ),
            ),
        )
        # Build a minimal proposal-like object for _denied.
        proposal = Proposal(
            proposal_id='TMS-STALE',
            change=ProposedChange(
                kind='transition_status',
                payload={'taskId': task_id},
            ),
            snapshot_hash='',
        )
        return self._denied(
            proposal,
            task_id=task_id,
            issues=(issue,),
            result='stale',
            derived_facts=tuple(f'Stale({aid})' for aid in stale_assertions),
            proof_trace=(
                {
                    'rule': 'LKB-TMS-001',
                    'premises': [f'Task({task_id})']
                    + [f'Stale({aid})' for aid in stale_assertions],
                    'conclusion': f'Not(CanMoveTo({task_id}, _))',
                    'solverVersion': self.solver_version,
                },
            ),
        )

    def _register_assertion_in_tms(
        self,
        context: 'ToolContext',
        *,
        assertion_id: str,
        worlds: tuple['World', ...],
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
        context: 'ToolContext',
        assumption_id: str,
        clarification: 'Clarification',
    ) -> tuple['AssumptionRecord', 'AssumptionRecord' | None, ValidationRun | None]:
        """Apply a user clarification and revalidate affected tasks.

        Returns the new/old assumption records and, if a single task was
        affected and the clarification resolves all stale dependencies, a
        fresh validation run for that task's current transition intent.
        """
        from .fuzzy_types import Clarification

        if not isinstance(clarification, Clarification):
            raise TypeError('clarification must be a Clarification instance')
        tms = self._tms(context)
        new_record, old_record = tms.clarify_assumption(assumption_id, clarification)
        validation_run: ValidationRun | None = None

        # F-139: an override creates a new active assumption and supersedes the
        # old one.  Log an explicit human-override audit event.
        if old_record is not None:
            assertion = tms.get_assertion(old_record.assertion_id)
            task_ids = tuple(assertion.task_ids) if assertion else ()
            _audit_log(context).append(
                event_for_human_override(
                    assumption_id=old_record.assumption_id,
                    assertion_id=old_record.assertion_id,
                    actor=getattr(clarification, 'actor', None) or 'system',
                    reason=getattr(clarification, 'reason', '') or 'user override',
                    previous_result=old_record.status,
                    task_ids=task_ids,
                    session_id=_session_id(context),
                )
            )

        affected = tms.get_stale_task_ids()
        if len(affected) == 0:
            # No remaining stale tasks; revalidate any previously affected task
            # that is now ready again.  We use the task linked to the clarified
            # assumption's assertion if exactly one exists.
            assertion = tms.get_assertion(new_record.assertion_id)
            task_ids = assertion.task_ids if assertion else set()
            if len(task_ids) == 1:
                task_id = next(iter(task_ids))
                task = (getattr(context, 'tasks', {}) or {}).get(task_id)
                if isinstance(task, dict) and task.get('status') == 'pending':
                    _audit_log(context).append(
                        event_for_revalidation_requested(
                            task_id,
                            triggered_by=f'assumption_clarified:{assumption_id}',
                            previous_validation_run_id=None,
                            session_id=_session_id(context),
                            actor=getattr(clarification, 'actor', None) or 'system',
                        )
                    )
                    change = ProposedChange(
                        kind='transition_status',
                        payload={'taskId': task_id, 'status': 'in_progress'},
                    )
                    validation_run = self.run(change, context)[1]
        return new_record, old_record, validation_run
