"""Internal data contracts for Logical Kanban (lkb)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

# ── 独立类型：替代 clawcodex_ext 耦合 ──────────────────────────────


@dataclass(frozen=True)
class LkbChatMessage:
    """lkb-local replacement for clawcodex_ext.providers.base.ChatMessage.

    Compatible with any BaseProvider that accepts objects with .role/.content attrs.
    """

    role: str
    content: str


@dataclass(frozen=True)
class LkbToolResult:
    """lkb-local replacement for clawcodex_ext.tool_system.protocol.ToolResult.

    Mirrors the 3 fields lkb actually uses. Independent of clawcodex_ext.tool_system.
    """

    name: str
    output: Any
    is_error: bool = False


@dataclass(slots=True)
class LkbValidationContext:
    """lkb-local minimal context for internal validation.

    Mirrors the 3 fields lkb actually uses in _build_validation_context.
    Duck-compatible with any object exposing .workspace_root / .session_id / .tasks.
    """

    workspace_root: Path
    session_id: str | None = None
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)


class ProviderLike(Protocol):
    """Minimal protocol — lkb only needs .chat(messages)."""

    def chat(self, messages: list[Any]) -> Any: ...


# ── 原有 types.py 内容（完整保留，lkb 独立所需） ────────────────────

ChangeKind = Literal[
    "create_task",
    "update_task_fields",
    "transition_status",
    "delete_task",
    "add_dependency",
    "remove_dependency",
    "legacy_todo_replace_all",
    "propose_assertion",
]

RepairAction = Literal[
    "complete_prerequisite",
    "remove_dependency",
    "fix_cycle",
    "add_acceptance_proof",
    "clarify_ambiguity",
    "revalidate_task",
    "split_task",
    "keep_single_in_progress",  # legacy TodoWrite compatibility
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
    action: RepairAction
    target: str | None = None
    assertion_id: str | None = None
    message: str = ""
    priority: int = 1

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"action": self.action}
        if self.target is not None:
            out["target"] = self.target
        if self.assertion_id is not None:
            out["assertionId"] = self.assertion_id
        if self.message:
            out["message"] = self.message
        if self.priority != 1:
            out["priority"] = self.priority
        return out


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
    """Immutable record of a single LKB validation run (F-133)."""

    validation_run_id: str
    proposal_id: str
    task_id: str | None = None

    input_facts_hash: str = ""
    ruleset_hash: str = ""
    snapshot_hash: str = ""

    engine: str = "layer1-python"
    engine_version: str = ""

    result: ValidationResult = "pass"
    duration_ms: int = 0

    derived_facts: tuple[str, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()
    counterexample: dict[str, Any] | None = None
    proof_enrichment: dict[str, Any] | None = None
    repair_suggestions: tuple[RepairSuggestion, ...] = ()

    issues: tuple[ValidationIssue, ...] = ()

    created_at: str = ""
    requested_by: str = "system"

    solver_results: tuple[dict[str, Any], ...] = ()

    legacy_todo_ambiguities: tuple[dict[str, Any], ...] = ()

    @property
    def validation_id(self) -> str:
        return self.validation_run_id

    @property
    def status(self) -> Literal["accepted", "denied"]:
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
            "proofEnrichment": self.proof_enrichment,
            "repairSuggestions": [s.to_dict() for s in self.repair_suggestions],
            "createdAt": self.created_at,
            "requestedBy": self.requested_by,
            "solverResults": list(self.solver_results),
        }
        if self.issues:
            out["issues"] = [issue.to_dict() for issue in self.issues]
        if self.legacy_todo_ambiguities:
            out["legacyTodoAmbiguities"] = list(self.legacy_todo_ambiguities)
        return out


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    proposal_id: str
    validation_run_id: str
    reason: dict[str, Any] | None = None
    derived_facts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "committed": self.committed,
            "proposalId": self.proposal_id,
            "validationRunId": self.validation_run_id,
            "reason": self.reason,
            "derivedFacts": list(self.derived_facts),
        }


DerivedStatus = Literal["ready", "blocked", "needs_recheck", "needs_review"]


@dataclass(frozen=True, slots=True)
class LkbStatus:
    """Compact LKB-derived status for UI rendering."""

    derived_status: DerivedStatus = "ready"
    validation_result: ValidationResult | None = None
    blocked_by: tuple[str, ...] = ()
    stale_assumptions: tuple[str, ...] = ()
    has_pending_clarification: bool = False

    @property
    def is_blocked(self) -> bool:
        return self.derived_status == "blocked"

    @property
    def has_issues(self) -> bool:
        return self.derived_status in ("blocked", "needs_recheck") or bool(self.stale_assumptions)