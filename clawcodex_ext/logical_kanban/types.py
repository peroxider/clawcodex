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


@dataclass(frozen=True)
class ValidationRun:
    validation_id: str
    proposal_id: str
    status: Literal["accepted", "denied"]
    issues: tuple[ValidationIssue, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()
    derived_facts: tuple[str, ...] = ()
    snapshot_hash: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "validationId": self.validation_id,
            "proposalId": self.proposal_id,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "proofTrace": list(self.proof_trace),
            "derivedFacts": list(self.derived_facts),
            "snapshotHash": self.snapshot_hash,
        }


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    proposal_id: str
    validation_id: str
    reason: dict[str, Any] | None = None
    derived_facts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed,
            "proposalId": self.proposal_id,
            "validationId": self.validation_id,
            "derivedFacts": list(self.derived_facts),
            **({"reason": self.reason} if self.reason is not None else {}),
        }
