"""Data contracts for the F-134 fuzzy input and multi-world handling layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .ir import CanonicalAssertion

AmbiguityKind = Literal[
    "lexical",
    "semantic_vagueness",
    "missing_subject",
    "missing_object",
    "unclear_dependency_direction",
    "temporal",
    "resource",
    "acceptance_criteria",
    "confidence_below_threshold",
]

Severity = Literal["critical", "major", "minor", "negligible"]

AssumptionSource = Literal[
    "user_input",
    "default_kb",
    "inferred",
    "user_clarified",
    "datalog_derived",
    "llm_extracted",
    "web_search",
    "agent_inferred",
]

DetectionMethod = Literal[
    "datalog_rules",
    "asp_enumeration",
    "llm_fallback",
]

AggregationStrategy = Literal[
    "unanimous_pass",
    "divergent_conclusions",
    "partial_pass",
    "unanimous_fail",
    "incomplete",
]

AggregationAction = Literal[
    "commit",
    "request_clarification",
    "reject",
    "wait",
]

ClarificationAction = Literal[
    "confirm",
    "override",
    "provide_info",
    "rephrase",
]

ValidationResultForWorld = Literal["pass", "fail", "unknown", "timeout", "pending"]


@dataclass(frozen=True, slots=True)
class Interpretation:
    """A single candidate reading of an ambiguous phrase."""

    code: str
    formalization: str
    base_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "formalization": self.formalization,
            "baseConfidence": self.base_confidence,
        }


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """One detected ambiguity point inside a natural-language assertion."""

    phrase: str
    kind: AmbiguityKind
    severity: Severity
    candidate_interpretations: tuple[Interpretation, ...] = ()
    resolved: bool = False
    resolution_method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "phrase": self.phrase,
            "kind": self.kind,
            "severity": self.severity,
            "candidateInterpretations": [i.to_dict() for i in self.candidate_interpretations],
            "resolved": self.resolved,
        }
        if self.resolution_method is not None:
            out["resolutionMethod"] = self.resolution_method
        return out


@dataclass(frozen=True, slots=True)
class Assumption:
    """A provisional value that a world depends on."""

    assumption_id: str
    assertion_id: str
    field: str
    assumed_value: str
    confidence: float
    source: AssumptionSource = "default_kb"
    source_ref: str = ""
    needs_clarification: bool = True
    clarification_prompt: str = ""
    created_at: str = ""
    clarified_at: str | None = None
    invalidated_at: str | None = None
    invalidated_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "assumptionId": self.assumption_id,
            "assertionId": self.assertion_id,
            "field": self.field,
            "assumedValue": self.assumed_value,
            "confidence": self.confidence,
            "source": self.source,
            "sourceRef": self.source_ref,
            "needsClarification": self.needs_clarification,
            "clarificationPrompt": self.clarification_prompt,
            "createdAt": self.created_at,
        }
        if self.clarified_at is not None:
            out["clarifiedAt"] = self.clarified_at
        if self.invalidated_at is not None:
            out["invalidatedAt"] = self.invalidated_at
        if self.invalidated_reason is not None:
            out["invalidatedReason"] = self.invalidated_reason
        return out


@dataclass(frozen=True, slots=True)
class AmbiguityReport:
    """Structured report of all ambiguities found in one assertion."""

    assertion_id: str
    detected_ambiguities: tuple[Ambiguity, ...] = ()
    severity: Severity = "negligible"
    needs_clarification: bool = False
    detection_method: DetectionMethod = "datalog_rules"
    processing_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertionId": self.assertion_id,
            "detectedAmbiguities": [a.to_dict() for a in self.detected_ambiguities],
            "severity": self.severity,
            "needsClarification": self.needs_clarification,
            "detectionMethod": self.detection_method,
            "processingTimeMs": self.processing_time_ms,
        }


@dataclass(frozen=True, slots=True)
class World:
    """One possible interpretation of an ambiguous assertion."""

    world_id: str
    confidence: float
    canonical_ir: CanonicalAssertion
    assumptions: tuple[Assumption, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "worldId": self.world_id,
            "confidence": self.confidence,
            "canonicalIr": self.canonical_ir.to_dict(),
            "assumptions": [a.to_dict() for a in self.assumptions],
        }


@dataclass(frozen=True, slots=True)
class MultiWorldResult:
    """Output of the ambiguity detector + world generator."""

    assertion_id: str
    ambiguity_report: AmbiguityReport
    worlds: tuple[World, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertionId": self.assertion_id,
            "ambiguityReport": self.ambiguity_report.to_dict(),
            "worlds": [w.to_dict() for w in self.worlds],
        }


@dataclass(frozen=True, slots=True)
class WorldValidationResult:
    """Validation outcome for a single world."""

    world_id: str
    result: ValidationResultForWorld
    conclusion_hash: str = ""
    derived_facts: tuple[str, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "worldId": self.world_id,
            "result": self.result,
            "conclusionHash": self.conclusion_hash,
            "derivedFacts": list(self.derived_facts),
            "proofTrace": list(self.proof_trace),
        }


@dataclass(frozen=True, slots=True)
class AggregationDecision:
    """Result of aggregating per-world validation results."""

    strategy: AggregationStrategy
    action: AggregationAction
    explanation: dict[str, str]
    world_results: tuple[WorldValidationResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "action": self.action,
            "explanation": dict(self.explanation),
            "worldResults": [w.to_dict() for w in self.world_results],
        }


@dataclass(frozen=True, slots=True)
class CommitDecision:
    """Final fuzzy-layer commit gate decision."""

    commit: bool
    reason: str = ""
    human_message: dict[str, str] = field(default_factory=dict)
    worlds: tuple[World, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "commit": self.commit,
            "reason": self.reason,
            "humanMessage": dict(self.human_message),
        }
        if self.worlds is not None:
            out["worlds"] = [w.to_dict() for w in self.worlds]
        return out


@dataclass(frozen=True, slots=True)
class Clarification:
    """User-provided clarification for an assumption."""

    assumption_id: str
    action: ClarificationAction
    new_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptionId": self.assumption_id,
            "action": self.action,
            "newValue": self.new_value,
        }


__all__ = [
    "AggregationAction",
    "AggregationDecision",
    "AggregationStrategy",
    "Ambiguity",
    "AmbiguityKind",
    "AmbiguityReport",
    "Assumption",
    "AssumptionSource",
    "Clarification",
    "ClarificationAction",
    "CommitDecision",
    "DetectionMethod",
    "Interpretation",
    "MultiWorldResult",
    "Severity",
    "ValidationResultForWorld",
    "World",
    "WorldValidationResult",
]
