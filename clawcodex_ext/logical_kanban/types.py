"""Internal data contracts for Logical Kanban."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChangeKind = Literal["todo_write", "task_update"]


@dataclass(frozen=True)
class FactsSnapshot:
    todos: tuple[dict[str, Any], ...] = ()
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    task_id: str | None = None
    blockers: tuple[str, ...] = ()
    repair_suggestions: tuple[RepairSuggestion, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "rule": self.rule,
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
            "snapshotHash": self.snapshot_hash,
        }


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    proposal_id: str
    validation_id: str
    reason: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed,
            "proposalId": self.proposal_id,
            "validationId": self.validation_id,
            **({"reason": self.reason} if self.reason is not None else {}),
        }
