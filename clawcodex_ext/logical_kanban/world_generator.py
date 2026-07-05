"""Multi-world generator for ambiguous assertions.

Given an AmbiguityReport, the generator enumerates all consistent combinations
of candidate interpretations (Cartesian product with domain-constraint
pruning), builds a CanonicalAssertion for each combination, attaches the
assumptions, and normalises world confidences so they sum to 1.0.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .fuzzy_types import Ambiguity, Assumption, AssumptionSource, World
from .ir import and_, pred

if TYPE_CHECKING:
    from .fuzzy_patterns import FuzzyPatternLibrary
    from .fuzzy_types import AmbiguityReport, Interpretation
    from .ir import CanonicalAssertion


def _new_assumption_id() -> str:
    return f"H-{uuid.uuid4().hex[:12]}"


def _field_for_kind(kind: str) -> str:
    mapping = {
        "semantic_vagueness": "meaning",
        "unclear_dependency_direction": "dependency_direction",
        "missing_subject": "subject",
        "missing_object": "object",
        "temporal": "time",
        "resource": "resource",
        "acceptance_criteria": "acceptance",
        "lexical": "word_sense",
        "confidence_below_threshold": "confidence",
    }
    return mapping.get(kind, kind)


def _source_for_confidence(confidence: float) -> AssumptionSource:
    if confidence >= 0.95:
        return "user_input"
    if confidence >= 0.7:
        return "datalog_derived"
    if confidence >= 0.5:
        return "inferred"
    return "default_kb"


def _prompt_for(ambiguity: Ambiguity, interpretation: "Interpretation") -> str:
    if ambiguity.kind == "unclear_dependency_direction":
        return "请明确依赖方向。"
    if ambiguity.kind == "missing_subject":
        return "请补充主体信息。"
    return f"假设采用解释“{interpretation.code}”，是否正确？"


class WorldGenerator:
    """Generate possible worlds from an ambiguity report."""

    def __init__(self, library: "FuzzyPatternLibrary | None" = None) -> None:
        from .fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY

        self.library = library or BUILT_IN_PATTERN_LIBRARY

    def generate(
        self,
        report: "AmbiguityReport",
        base_assertion: "CanonicalAssertion",
    ) -> list[World]:
        """Return all consistent worlds for ``report``.

        Each world contains a CanonicalAssertion that reflects one concrete
        combination of interpretations, plus the assumptions that were made to
        produce that world.
        """
        ambiguities = list(report.detected_ambiguities)
        if not ambiguities:
            return [
                World(
                    world_id="W-1",
                    confidence=1.0,
                    canonical_ir=base_assertion,
                    assumptions=(),
                )
            ]

        # Build candidate lists: each item carries (ambiguity_index, interpretation).
        candidates = [
            [
                (amb_idx, amb.candidate_interpretations[interp_idx])
                for interp_idx in range(len(amb.candidate_interpretations))
            ]
            for amb_idx, amb in enumerate(ambiguities)
        ]
        raw_combinations = list(itertools.product(*candidates))
        valid_combinations = self._prune(raw_combinations)

        worlds = self._build_worlds(
            valid_combinations,
            ambiguities,
            report.assertion_id,
            base_assertion,
        )
        return self._normalise_confidences(worlds)

    def _prune(
        self,
        combinations: list[tuple],
    ) -> list[tuple]:
        """Remove interpretation combinations that violate domain constraints."""
        valid: list[tuple] = []
        for combo in combinations:
            selected_codes = {interpretation.code for _, interpretation in combo}
            blocked = any(
                constraint.blocks.issubset(selected_codes)
                for constraint in self.library.constraints
            )
            if not blocked:
                valid.append(combo)
        return valid

    def _build_worlds(
        self,
        combinations: list[tuple],
        ambiguities: list[Ambiguity],
        assertion_id: str,
        base_assertion: "CanonicalAssertion",
    ) -> list[World]:
        worlds: list[World] = []
        timestamp = datetime.now(timezone.utc).isoformat()
        for combo_index, combo in enumerate(combinations, start=1):
            assumptions: list[Assumption] = []
            assumption_nodes: list = []
            raw_confidence = 1.0
            for amb_idx, interpretation in combo:
                ambiguity = ambiguities[amb_idx]
                raw_confidence *= interpretation.base_confidence
                assumption_id = _new_assumption_id()
                assumptions.append(
                    Assumption(
                        assumption_id=assumption_id,
                        assertion_id=assertion_id,
                        field=_field_for_kind(ambiguity.kind),
                        assumed_value=interpretation.code,
                        confidence=interpretation.base_confidence,
                        source=_source_for_confidence(interpretation.base_confidence),
                        source_ref=ambiguity.kind,
                        needs_clarification=True,
                        clarification_prompt=_prompt_for(ambiguity, interpretation),
                        created_at=timestamp,
                    )
                )
                assumption_nodes.append(
                    pred("Assumes", assertion_id, assumption_id, interpretation.code)
                )
            body = base_assertion.body
            if assumption_nodes:
                body = and_(body, *assumption_nodes)
            world_ir = base_assertion.__class__(
                role=base_assertion.role,
                kind=base_assertion.kind,
                body=body,
                quantifier=base_assertion.quantifier,
                vars=base_assertion.vars,
                schema_version=base_assertion.schema_version,
            )
            worlds.append(
                World(
                    world_id=f"W-{combo_index}",
                    confidence=raw_confidence,
                    canonical_ir=world_ir,
                    assumptions=tuple(assumptions),
                )
            )
        return worlds

    def _normalise_confidences(self, worlds: list[World]) -> list[World]:
        total = sum(w.confidence for w in worlds)
        if total <= 0 or len(worlds) == 1:
            if worlds:
                worlds[0] = World(
                    world_id=worlds[0].world_id,
                    confidence=1.0,
                    canonical_ir=worlds[0].canonical_ir,
                    assumptions=worlds[0].assumptions,
                )
            return worlds
        normalised: list[World] = []
        for w in worlds:
            normalised.append(
                World(
                    world_id=w.world_id,
                    confidence=round(w.confidence / total, 4),
                    canonical_ir=w.canonical_ir,
                    assumptions=w.assumptions,
                )
            )
        # Fix any residual rounding error on the largest world so the sum is exactly 1.0.
        residual = 1.0 - sum(w.confidence for w in normalised)
        if normalised and abs(residual) > 0:
            largest_idx = max(range(len(normalised)), key=lambda i: normalised[i].confidence)
            largest = normalised[largest_idx]
            normalised[largest_idx] = World(
                world_id=largest.world_id,
                confidence=round(largest.confidence + residual, 6),
                canonical_ir=largest.canonical_ir,
                assumptions=largest.assumptions,
            )
        return normalised


__all__ = ["WorldGenerator"]
