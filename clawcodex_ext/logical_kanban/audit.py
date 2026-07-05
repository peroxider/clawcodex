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
    "default_session_log_path",
    "event_for_assumption_invalidated",
    "event_for_commit",
    "event_for_human_override",
    "event_for_proposal",
    "event_for_revalidation_requested",
    "event_for_validation_run",
    "get_audit_log",
]
