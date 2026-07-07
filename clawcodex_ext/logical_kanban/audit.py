"""Audit logging for Logical Kanban.

F-137 MVP persistence layer.  The audit log records enough state to make LKB
validation explainable and reproducible within a session without requiring the
orchestrator or an external database.

Storage strategy:
* In-memory buffer attached to the runtime (always available).
* Optional session-local append log at ``~/.clawcodex/lkb/<session_id>/events.ndjson``.

The append log is written line-by-line so crashes never corrupt prior events.
Events are NDJSON objects with a stable canonical schema.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .types import CommitResult, Proposal, ProposedChange, ValidationRun


AuditEventType = Literal[
    "lkb_proposal_created",
    "lkb_validation_run",
    "lkb_commit",
    "lkb_denial",
    "lkb_assumption_invalidated",
    "lkb_revalidation_requested",
    "lkb_human_override",
    "lkb_proof_enrichment",
    "lkb_fact_extracted",
    "lkb_fact_dropped",
    "lkb_llm_fallback_used",
    "lkb_legacy_todo_ambiguity",
    "lkb_decomposition_proposed",
    "lkb_method_referenced",
    "lkb_acceptance_template_registered",
    "lkb_acceptance_template_referenced",
    "lkb_external_config_imported",
]


EventDecision = Literal["committed", "denied", "accepted", "stale", "error"]


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event record."""

    event_id: str
    event_type: AuditEventType
    actor: str
    timestamp: str
    session_id: str | None
    proposal_id: str | None
    validation_run_id: str | None
    task_id: str | None
    decision: EventDecision | None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "proposalId": self.proposal_id,
            "validationRunId": self.validation_run_id,
            "taskId": self.task_id,
            "decision": self.decision,
        }
        if self.session_id is not None:
            out["sessionId"] = self.session_id
        if self.payload:
            out["payload"] = self.payload
        return out


class AuditLog(ABC):
    """Abstract audit log sink."""

    @abstractmethod
    def append(self, event: AuditEvent) -> None:
        """Persist ``event`` to the log."""

    @abstractmethod
    def query(
        self,
        *,
        event_type: AuditEventType | None = None,
        proposal_id: str | None = None,
        validation_run_id: str | None = None,
        task_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[AuditEvent, ...]:
        """Return matching events, most recent first."""

    @abstractmethod
    def latest_for_task(self, task_id: str) -> dict[str, Any] | None:
        """Return the most recent denial for ``task_id``, if any."""


class InMemoryAuditLog(AuditLog):
    """Session-scoped in-memory audit log."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def query(
        self,
        *,
        event_type: AuditEventType | None = None,
        proposal_id: str | None = None,
        validation_run_id: str | None = None,
        task_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[AuditEvent, ...]:
        with self._lock:
            events = list(self._events)
        matches = _filter_events(
            events,
            event_type=event_type,
            proposal_id=proposal_id,
            validation_run_id=validation_run_id,
            task_id=task_id,
        )
        if limit is not None:
            matches = matches[-limit:]
        return tuple(reversed(matches))

    def latest_for_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            for event in reversed(self._events):
                if event.task_id == task_id and event.event_type == "lkb_denial":
                    return dict(event.payload.get("denial", {}))
        return None

    def all_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


class SessionFileAuditLog(AuditLog):
    """Session-local NDJSON append log.

    The log file is created lazily on first append and flushed after every
    write so a crash only loses the event currently in flight.
    """

    def __init__(self, path: Path | str, *, in_memory: InMemoryAuditLog | None = None) -> None:
        self._path = Path(path)
        self._memory = in_memory or InMemoryAuditLog()
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, event: AuditEvent) -> None:
        self._memory.append(event)
        line = json.dumps(event.to_dict(), sort_keys=True, default=str)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()

    def query(
        self,
        *,
        event_type: AuditEventType | None = None,
        proposal_id: str | None = None,
        validation_run_id: str | None = None,
        task_id: str | None = None,
        limit: int | None = None,
    ) -> tuple[AuditEvent, ...]:
        return self._memory.query(
            event_type=event_type,
            proposal_id=proposal_id,
            validation_run_id=validation_run_id,
            task_id=task_id,
            limit=limit,
        )

    def latest_for_task(self, task_id: str) -> dict[str, Any] | None:
        return self._memory.latest_for_task(task_id)

    def all_events(self) -> tuple[AuditEvent, ...]:
        return self._memory.all_events()


def _filter_events(
    events: list[AuditEvent],
    *,
    event_type: AuditEventType | None,
    proposal_id: str | None,
    validation_run_id: str | None,
    task_id: str | None,
) -> list[AuditEvent]:
    matches: list[AuditEvent] = []
    for event in events:
        if event_type is not None and event.event_type != event_type:
            continue
        if proposal_id is not None and event.proposal_id != proposal_id:
            continue
        if validation_run_id is not None and event.validation_run_id != validation_run_id:
            continue
        if task_id is not None and event.task_id != task_id:
            continue
        matches.append(event)
    return matches


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    import uuid

    return f"E-{uuid.uuid4().hex[:12]}"


def _decision_from_validation(validation: ValidationRun) -> EventDecision:
    if validation.result == "pass":
        return "accepted"
    if validation.result == "stale":
        return "stale"
    return "denied"


def event_for_proposal(
    proposal: Proposal,
    *,
    session_id: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_proposal_created",
        actor=proposal.change.actor or "system",
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=proposal.proposal_id,
        validation_run_id=None,
        task_id=_task_id_from_change(proposal.change),
        decision=None,
        payload={
            "changeKind": proposal.change.kind,
            "snapshotHash": proposal.snapshot_hash,
            "reason": proposal.change.reason,
        },
    )


def event_for_validation_run(
    proposal: Proposal,
    validation: ValidationRun,
    *,
    session_id: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_validation_run",
        actor=validation.requested_by,
        timestamp=validation.created_at or _utc_now(),
        session_id=session_id,
        proposal_id=proposal.proposal_id,
        validation_run_id=validation.validation_run_id,
        task_id=validation.task_id or _task_id_from_change(proposal.change),
        decision=_decision_from_validation(validation),
        payload={
            "result": validation.result,
            "engine": validation.engine,
            "engineVersion": validation.engine_version,
            "inputFactsHash": validation.input_facts_hash,
            "rulesetHash": validation.ruleset_hash,
            "durationMs": validation.duration_ms,
            "issueCount": len(validation.issues),
        },
    )


def event_for_commit(
    proposal: Proposal,
    validation: ValidationRun,
    commit: CommitResult,
    *,
    session_id: str | None = None,
) -> AuditEvent:
    event_type: AuditEventType = "lkb_commit" if commit.committed else "lkb_denial"
    return AuditEvent(
        event_id=_new_event_id(),
        event_type=event_type,
        actor=validation.requested_by,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=proposal.proposal_id,
        validation_run_id=validation.validation_run_id,
        task_id=validation.task_id or _task_id_from_change(proposal.change),
        decision="committed" if commit.committed else "denied",
        payload={
            "result": validation.result,
            "validation": validation.to_dict(),
            "commit": commit.to_dict(),
            "denial": None if commit.committed else _denial_payload(validation),
        },
    )


def event_for_assumption_invalidated(
    assumption_id: str,
    assertion_id: str,
    *,
    reason: str = "",
    task_ids: tuple[str, ...] = (),
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_assumption_invalidated",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=None,
        task_id=task_ids[0] if task_ids else None,
        decision=None,
        payload={
            "assumptionId": assumption_id,
            "assertionId": assertion_id,
            "reason": reason,
            "taskIds": list(task_ids),
        },
    )


def event_for_human_override(
    *,
    assumption_id: str,
    assertion_id: str,
    actor: str,
    reason: str,
    previous_result: str,
    task_ids: tuple[str, ...] = (),
    validation_run_id: str | None = None,
    session_id: str | None = None,
) -> AuditEvent:
    """Record an explicit human override of an LKB assumption/denial."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_human_override",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=task_ids[0] if task_ids else None,
        decision="committed",
        payload={
            "assumptionId": assumption_id,
            "assertionId": assertion_id,
            "reason": reason,
            "previousResult": previous_result,
            "taskIds": list(task_ids),
        },
    )


def event_for_revalidation_requested(
    task_id: str,
    *,
    triggered_by: str,
    previous_validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record a request to revalidate a task after a dependency/assumption change."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_revalidation_requested",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=previous_validation_run_id,
        task_id=task_id,
        decision=None,
        payload={
            "triggeredBy": triggered_by,
            "previousValidationRunId": previous_validation_run_id,
        },
    )


def event_for_proof_enrichment(
    validation: ValidationRun,
    *,
    adapter: str,
    proof_trace: tuple[dict[str, Any], ...] = (),
    counterexample: dict[str, Any] | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record asynchronous proof/countermodel enrichment for a validation run."""
    enrichment_key = f"{validation.validation_run_id}:{adapter}"
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_proof_enrichment",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=validation.proposal_id,
        validation_run_id=validation.validation_run_id,
        task_id=validation.task_id,
        decision=None,
        payload={
            "adapter": adapter,
            "enrichmentKey": enrichment_key,
            "proofTrace": list(proof_trace),
            "counterexample": counterexample,
        },
    )


def event_for_fact_extracted(
    *,
    assertion_hash: str,
    source: str,
    confidence: float,
    model_id: str,
    glossary_status: str = "valid",
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record a successfully extracted LLM-derived fact."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_fact_extracted",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision=None,
        payload={
            "assertionHash": assertion_hash,
            "source": source,
            "confidence": confidence,
            "modelId": model_id,
            "glossaryStatus": glossary_status,
            "enrichmentKey": f"{assertion_hash}:{source}",
        },
    )


def event_for_fact_dropped(
    *,
    assertion_hash: str,
    reason: str,
    unknown_predicates: tuple[str, ...] = (),
    model_id: str | None = None,
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record an LLM-derived fact that failed the glossary gate or confidence floor."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_fact_dropped",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision=None,
        payload={
            "assertionHash": assertion_hash,
            "reason": reason,
            "unknownPredicates": list(unknown_predicates),
            "modelId": model_id,
            "enrichmentKey": f"{assertion_hash}:{reason}",
        },
    )


def event_for_llm_fallback_used(
    *,
    phrase: str,
    kind: str,
    candidate_count: int,
    model_id: str,
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record an L3 ambiguity-detection fallback to the LLM."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_llm_fallback_used",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision=None,
        payload={
            "phrase": phrase,
            "kind": kind,
            "candidateCount": candidate_count,
            "modelId": model_id,
            "enrichmentKey": f"{phrase}:{model_id}",
        },
    )


def event_for_legacy_todo_ambiguity(
    todo_id: str,
    ambiguity_code: str,
    severity: str,
    clarification_prompt: str,
    *,
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record a critical/major ambiguity detected in a legacy TodoWrite todo."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_legacy_todo_ambiguity",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=todo_id,
        decision=None,
        payload={
            "todoId": todo_id,
            "ambiguityCode": ambiguity_code,
            "severity": severity,
            "clarificationPrompt": clarification_prompt,
            "enrichmentKey": f"{validation_run_id}:{todo_id}:{ambiguity_code}",
        },
    )


def event_for_decomposition_proposed(
    decomposition_run_id: str,
    goal: str,
    *,
    task_count: int,
    dependency_count: int,
    ambiguity_count: int,
    validation_run_id: str | None = None,
    result: str = "pass",
    session_id: str | None = None,
    actor: str = "agent",
) -> AuditEvent:
    """Record a task-decomposition proposal produced by TaskDecompose.

    F-149: one event per decomposition run so the audit trail can replay
    what the agent was offered before it chose to create/update tasks.
    """
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_decomposition_proposed",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision="accepted" if result == "pass" else "denied",
        payload={
            "decompositionRunId": decomposition_run_id,
            "goal": goal[:500],
            "taskCount": task_count,
            "dependencyCount": dependency_count,
            "ambiguityCount": ambiguity_count,
            "result": result,
            "enrichmentKey": decomposition_run_id,
        },
    )


def event_for_method_referenced(
    decomposition_run_id: str,
    method_id: str,
    *,
    task_count: int,
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "agent",
) -> AuditEvent:
    """Record that the LLM anchored at least one task to ``method_id``.

    F-151: one event per method-library reference surfaced in a
    decomposition plan.  Emitted *after* the plan is validated so
    downstream consumers can compute method-reuse ratios per session
    without scraping ``lkb_decomposition_proposed`` payloads.

    The event id is a content-derived hash so that re-emitting for the
    same (run, method) pair is naturally idempotent.
    """
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_method_referenced",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision=None,
        payload={
            "decompositionRunId": decomposition_run_id,
            "methodId": method_id,
            "taskCount": task_count,
            "enrichmentKey": f"{decomposition_run_id}:{method_id}",
        },
    )


def event_for_acceptance_template_registered(
    *,
    template_id: str,
    source: str,
    version: str,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record that a top-level acceptance template was registered."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_acceptance_template_registered",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=None,
        task_id=None,
        decision="accepted",
        payload={
            "templateId": template_id,
            "source": source,
            "version": version,
            "enrichmentKey": f"{source}:{template_id}:{version}",
        },
    )


def event_for_acceptance_template_referenced(
    decomposition_run_id: str,
    template_id: str,
    *,
    task_count: int,
    validation_run_id: str | None = None,
    session_id: str | None = None,
    actor: str = "agent",
) -> AuditEvent:
    """Record that a decomposition plan referenced an acceptance template."""
    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_acceptance_template_referenced",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=validation_run_id,
        task_id=None,
        decision=None,
        payload={
            "decompositionRunId": decomposition_run_id,
            "templateId": template_id,
            "taskCount": task_count,
            "enrichmentKey": f"{decomposition_run_id}:{template_id}",
        },
    )


def event_for_external_config_imported(
    *,
    source: str,
    kind: str,
    version: str = "",
    item_count: int,
    lint_issue_count: int,
    lint_error_count: int,
    session_id: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    """Record an external LKB configuration import (F-154)."""

    return AuditEvent(
        event_id=_new_event_id(),
        event_type="lkb_external_config_imported",
        actor=actor,
        timestamp=_utc_now(),
        session_id=session_id,
        proposal_id=None,
        validation_run_id=None,
        task_id=None,
        decision="accepted" if lint_error_count == 0 else "error",
        payload={
            "source": source,
            "kind": kind,
            "version": version,
            "itemCount": item_count,
            "lintIssueCount": lint_issue_count,
            "lintErrorCount": lint_error_count,
            "enrichmentKey": f"{source}:{kind}:{version}",
        },
    )


def append_event_once(
    audit_log: AuditLog,
    event: AuditEvent,
    *,
    event_type: str | None = None,
) -> bool:
    """Append ``event`` unless the same enrichment key is already present.

    ``event_type`` defaults to ``event.event_type`` so callers can rely on the
    event's own type for the idempotency query.
    """
    key = event.payload.get("enrichmentKey")
    query_type = event_type or event.event_type
    for existing in audit_log.query(
        event_type=query_type,
        validation_run_id=event.validation_run_id,
    ):
        if existing.payload.get("enrichmentKey") == key:
            return False
    audit_log.append(event)
    return True


def append_proof_enrichment_once(audit_log: AuditLog, event: AuditEvent) -> bool:
    """Append ``event`` unless the same enrichment key is already present."""
    return append_event_once(audit_log, event, event_type="lkb_proof_enrichment")


def _denial_payload(validation: ValidationRun) -> dict[str, Any]:
    return {
        "validationRunId": validation.validation_run_id,
        "proposalId": validation.proposal_id,
        "taskId": validation.task_id,
        "result": validation.result,
        "humanMessage": validation.issues[0].message if validation.issues else "Validation denied.",
        "issues": [issue.to_dict() for issue in validation.issues],
        "counterexample": validation.counterexample,
        "repairSuggestions": [s.to_dict() for s in validation.repair_suggestions],
    }


def _task_id_from_change(change: ProposedChange) -> str | None:
    payload = change.payload
    if not isinstance(payload, dict):
        return None
    task_id = payload.get("taskId")
    return task_id if isinstance(task_id, str) else None


def default_session_log_path(session_id: str | None) -> Path | None:
    """Return the default session-local append log path.

    Returns ``None`` when ``session_id`` is empty so callers fall back to the
    in-memory log only.
    """
    if not session_id:
        return None
    return Path.home() / ".clawcodex" / "lkb" / session_id / "events.ndjson"


def get_audit_log(context: Any) -> AuditLog:
    """Return the audit log for ``context``, creating one if necessary."""
    from .runtime import get_logical_kanban

    runtime = get_logical_kanban(context)
    audit_log = getattr(runtime, "audit_log", None)
    if audit_log is not None:
        return audit_log

    session_id = getattr(context, "session_id", None)
    log_path = default_session_log_path(session_id)
    if log_path is not None:
        audit_log = SessionFileAuditLog(log_path)
    else:
        audit_log = InMemoryAuditLog()
    runtime.audit_log = audit_log
    return audit_log


__all__ = [
    "AuditEvent",
    "AuditEventType",
    "AuditLog",
    "EventDecision",
    "InMemoryAuditLog",
    "SessionFileAuditLog",
    "append_event_once",
    "append_proof_enrichment_once",
    "default_session_log_path",
    "event_for_assumption_invalidated",
    "event_for_commit",
    "event_for_decomposition_proposed",
    "event_for_acceptance_template_referenced",
    "event_for_acceptance_template_registered",
    "event_for_external_config_imported",
    "event_for_fact_dropped",
    "event_for_fact_extracted",
    "event_for_human_override",
    "event_for_legacy_todo_ambiguity",
    "event_for_llm_fallback_used",
    "event_for_method_referenced",
    "event_for_proof_enrichment",
    "event_for_proposal",
    "event_for_revalidation_requested",
    "event_for_validation_run",
    "get_audit_log",
]
