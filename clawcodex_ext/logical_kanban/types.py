"""Internal data contracts for Logical Kanban."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChangeKind = Literal[
    "create_task",
    "update_task_fields",
    "transition_status",
    "delete_task",
    "add_dependency",
    "remove_dependency",
    "legacy_todo_replace_all",
]


@dataclass(frozen=True)
class FactsSnapshot:
    todos: tuple[dict[str, Any], ...] = ()
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    normalized_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    facts: tuple[str, ...] = ()
    completed_ids: frozenset[str] = field(default_factory=frozenset)
    dependency_graph: dict[str, tuple[str, ...]] = field(default_factory=dict)
    blocked_by: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ready_ids: frozenset[str] = field(default_factory=frozenset)
    blocked_ids: frozenset[str] = field(default_factory=frozenset)
    cycle_task_ids: frozenset[str] = field(default_factory=frozenset)
    warnings: tuple["ValidationIssue", ...] = ()
    hash: str = ""


@dataclass(frozen=True)
class ProposedChange:
    kind: ChangeKind
    payload: dict[str, Any]
    actor: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    change: ProposedChange
    snapshot_hash: str


@dataclass(frozen=True)
class RepairSuggestion:
    action: str
    target: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            **({"target": self.target} if self.target else {}),
            **({"message": self.message} if self.message else {}),
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    rule: str
    severity: Literal["warning", "error"] = "error"
    task_id: str | None = None
    blockers: tuple[str, ...] = ()
    repair_suggestions: tuple[RepairSuggestion, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "rule": self.rule,
            "severity": self.severity,
            **({"taskId": self.task_id} if self.task_id else {}),
            **({"blockers": list(self.blockers)} if self.blockers else {}),
            "repairSuggestions": [s.to_dict() for s in self.repair_suggestions],
        }


ValidationResult = Literal[
    "pass",
    "fail",
    "unknown",
    "timeout",
    "error",
    "stale",
]


@dataclass(frozen=True)
class ValidationRun:
    """Immutable record of a single LKB validation run (F-133).

    The field names follow the canonical ValidationRun contract so that the
    structure can be returned to the model, displayed in the TUI, and persisted
    for audit.  The class is frozen; once created it cannot be mutated.
    """

    # Canonical F-133 identity
    validation_run_id: str
    proposal_id: str
    task_id: str | None = None

    # Reproducibility hashes
    input_facts_hash: str = ""
    ruleset_hash: str = ""
    snapshot_hash: str = ""  # legacy alias kept for internal consumers

    # Engine metadata
    engine: str = "layer1-python"
    engine_version: str = ""

    # Result
    result: ValidationResult = "pass"
    duration_ms: int = 0

    # Evidence
    derived_facts: tuple[str, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()
    counterexample: dict[str, Any] | None = None
    repair_suggestions: tuple[RepairSuggestion, ...] = ()

    # Human-readable diagnostics (kept for internal adapter use)
    issues: tuple[ValidationIssue, ...] = ()

    # Audit
    created_at: str = ""  # ISO-8601 UTC
    requested_by: str = "system"

    @property
    def validation_id(self) -> str:
        """Backwards-compatible alias for :attr:`validation_run_id`."""
        return self.validation_run_id

    @property
    def status(self) -> Literal["accepted", "denied"]:
        """Backwards-compatible status derived from :attr:`result`."""
        return "accepted" if self.result == "pass" else "denied"

    @property
    def accepted(self) -> bool:
        return self.result == "pass"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "validationRunId": self.validation_run_id,
            "proposalId": self.proposal_id,
            "taskId": self.task_id,
            "inputFactsHash": self.input_facts_hash,
            "rulesetHash": self.ruleset_hash,
            "snapshotHash": self.snapshot_hash,
            "engine": self.engine,
            "engineVersion": self.engine_version,
            "result": self.result,
            "status": self.status,
            "durationMs": self.duration_ms,
            "derivedFacts": list(self.derived_facts),
            "proofTrace": list(self.proof_trace),
            "counterexample": self.counterexample,
            "repairSuggestions": [s.to_dict() for s in self.repair_suggestions],
            "createdAt": self.created_at,
            "requestedBy": self.requested_by,
        }
        if self.issues:
            out["issues"] = [issue.to_dict() for issue in self.issues]
        return out


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    proposal_id: str
    validation_run_id: str
    reason: dict[str, Any] | None = None
    derived_facts: tuple[str, ...] = ()

    @property
    def validation_id(self) -> str:
        """Backwards-compatible alias for :attr:`validation_run_id`."""
        return self.validation_run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed,
            "proposalId": self.proposal_id,
            "validationRunId": self.validation_run_id,
            "derivedFacts": list(self.derived_facts),
            **({"reason": self.reason} if self.reason is not None else {}),
        }
