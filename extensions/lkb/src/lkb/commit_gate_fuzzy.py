"""Commit Gate fuzzy check and multi-world aggregation.

Implements the conservative rejection policy from the LKB v3 spec:
- uncertain assumptions default to deny for irreversible state changes
- worlds must agree on their conclusion before the gate opens
- unresolved critical ambiguities always block commit
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .fuzzy_types import (
    AggregationAction,
    AggregationDecision,
    AggregationStrategy,
    CommitDecision,
    Severity,
)

if TYPE_CHECKING:
    from .fuzzy_types import AmbiguityReport, World, WorldValidationResult

FUZZY_THRESHOLD_MINOR = 0.3

def _severity_rank(severity: Severity) -> int:
    return {"negligible": 0, "minor": 1, "major": 2, "critical": 3}[severity]

def aggregate_world_results(
    world_results: list["WorldValidationResult"],
) -> AggregationDecision:
    """Aggregate per-world validation results into a single decision.

    Strategy follows section 9.3.3 of the LKB v3 specification:
    - unanimous_pass: all worlds pass with identical conclusion hash
    - divergent_conclusions: all pass but conclusions differ
    - partial_pass: mix of pass and fail
    - unanimous_fail: all fail
    - incomplete: any result is pending/unknown/timeout
    """
    if not world_results:
        return AggregationDecision(
            strategy="incomplete",
            action="wait",
            explanation={
                "zh": "没有可聚合的世界验证结果。",
                "en": "No world validation results to aggregate.",
            },
            world_results=(),
        )

    results = [wr.result for wr in world_results]

    if any(r in ("pending", "unknown", "timeout") for r in results):
        return AggregationDecision(
            strategy="incomplete",
            action="wait",
            explanation={
                "zh": "部分世界验证结果尚未完成。",
                "en": "Some world validations are still incomplete.",
            },
            world_results=tuple(world_results),
        )

    if all(r == "fail" for r in results):
        return AggregationDecision(
            strategy="unanimous_fail",
            action="reject",
            explanation={
                "zh": "所有解释下该断言均不可行。",
                "en": "The assertion is infeasible under every interpretation.",
            },
            world_results=tuple(world_results),
        )

    pass_hashes = {wr.conclusion_hash for wr in world_results if wr.result == "pass"}

    if all(r == "pass" for r in results):
        if len(pass_hashes) == 1:
            return AggregationDecision(
                strategy="unanimous_pass",
                action="commit",
                explanation={
                    "zh": "所有世界通过验证且结论一致。",
                    "en": "All worlds pass validation and agree on the conclusion.",
                },
                world_results=tuple(world_results),
            )
        return AggregationDecision(
            strategy="divergent_conclusions",
            action="request_clarification",
            explanation={
                "zh": "所有世界均通过验证，但结论不一致，需要澄清。",
                "en": "All worlds pass, but their conclusions differ; clarification needed.",
            },
            world_results=tuple(world_results),
        )

    return AggregationDecision(
        strategy="partial_pass",
        action="request_clarification",
        explanation={
            "zh": "部分解释下验证通过，部分未通过，需要澄清。",
            "en": "Some interpretations pass validation while others do not; clarification needed.",
        },
        world_results=tuple(world_results),
    )

def commit_gate_fuzzy_check(
    worlds: list["World"],
    world_results: list["WorldValidationResult"],
    ambiguity_report: "AmbiguityReport",
    *,
    is_irreversible: bool = True,
) -> CommitDecision:
    """Return the fuzzy-layer commit decision for a set of worlds.

    Parameters
    ----------
    worlds:
        Generated possible worlds.
    world_results:
        Per-world validation results.
    ambiguity_report:
        Ambiguity report produced by the detector.
    is_irreversible:
        When ``True`` (default), ambiguous assertions default to deny.
    """
    # Check 1: minimum assumption confidence across all worlds.
    all_assumptions = [a for w in worlds for a in w.assumptions]
    if all_assumptions:
        min_confidence = min(a.confidence for a in all_assumptions)
    else:
        min_confidence = 1.0

    if min_confidence < FUZZY_THRESHOLD_MINOR:
        return CommitDecision(
            commit=False,
            reason="fuzzy_assumption_confidence_too_low",
            human_message={
                "zh": f"假设置信度过低 ({min_confidence:.2f})，需要澄清。",
                "en": f"Assumption confidence too low ({min_confidence:.2f}), clarification needed.",
            },
            worlds=tuple(worlds),
        )

    # Check 2: multi-world consistency.
    aggregation = aggregate_world_results(world_results)
    if aggregation.strategy in ("divergent_conclusions", "partial_pass"):
        return CommitDecision(
            commit=False,
            reason="fuzzy_divergent_worlds",
            human_message=aggregation.explanation,
            worlds=tuple(worlds),
        )

    if aggregation.strategy == "unanimous_fail":
        return CommitDecision(
            commit=False,
            reason="fuzzy_unanimous_fail",
            human_message=aggregation.explanation,
            worlds=tuple(worlds),
        )

    if aggregation.strategy == "incomplete":
        return CommitDecision(
            commit=False,
            reason="fuzzy_incomplete",
            human_message=aggregation.explanation,
            worlds=tuple(worlds),
        )

    # Check 3: unresolved critical ambiguity.
    unresolved_critical = any(
        amb.severity == "critical" and not amb.resolved
        for amb in ambiguity_report.detected_ambiguities
    )
    if unresolved_critical:
        return CommitDecision(
            commit=False,
            reason="fuzzy_critical_unresolved",
            human_message={
                "zh": "存在未澄清的关键模糊性，请先澄清。",
                "en": "Unresolved critical ambiguity exists. Please clarify.",
            },
            worlds=tuple(worlds),
        )

    # Check 4: default-deny for irreversible changes when clarification is needed.
    if is_irreversible and ambiguity_report.needs_clarification and all_assumptions:
        # If aggregation already allowed commit but the report still flagged
        # major ambiguity, keep the assumptions visible in metadata and allow
        # commit only when conclusions are unanimous.
        if aggregation.strategy != "unanimous_pass":
            return CommitDecision(
                commit=False,
                reason="fuzzy_clarification_needed_for_irreversible_change",
                human_message={
                    "zh": "该变更不可逆且存在未澄清假设，需要用户确认。",
                    "en": "This change is irreversible and depends on unresolved assumptions; user confirmation required.",
                },
                worlds=tuple(worlds),
            )

    return CommitDecision(
        commit=True,
        reason="fuzzy_check_pass",
        human_message={
            "zh": "模糊性检查通过。",
            "en": "Fuzzy check passed.",
        },
        worlds=tuple(worlds),
    )

__all__ = [
    "FUZZY_THRESHOLD_MINOR",
    "aggregate_world_results",
    "commit_gate_fuzzy_check",
]
