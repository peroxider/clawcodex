"""Ambiguity detector for natural-language assertions.

The detector consumes a pattern library (by default the built-in F-134 library)
and produces an AmbiguityReport.  It intentionally does not call external
solvers; the matching logic is a direct Python translation of the Datalog
pattern rules described in the LKB v3 spec.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .fuzzy_types import Ambiguity, AmbiguityKind, AmbiguityReport, Interpretation, Severity

if TYPE_CHECKING:
    from .fuzzy_patterns import FuzzyPatternLibrary


def _max_severity(severities: list[Severity]) -> Severity:
    order = ("negligible", "minor", "major", "critical")
    if not severities:
        return "negligible"
    return max(severities, key=lambda s: order.index(s))


def _requires_clarification(ambiguities: list[Ambiguity]) -> bool:
    """Heuristic: ask for clarification when ambiguity can change conclusions."""
    for amb in ambiguities:
        if amb.severity in ("critical", "major"):
            return True
        if amb.kind in (
            "semantic_vagueness",
            "unclear_dependency_direction",
            "missing_subject",
            "missing_object",
        ):
            return True
    return False


class AmbiguityDetector:
    """Detect ambiguities in a natural-language assertion."""

    def __init__(self, library: "FuzzyPatternLibrary | None" = None) -> None:
        from .fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY

        self.library = library or BUILT_IN_PATTERN_LIBRARY

    def detect(
        self,
        text: str,
        *,
        assertion_id: str,
        context_facts: tuple[str, ...] = (),
    ) -> AmbiguityReport:
        """Return an AmbiguityReport for ``text``.

        Parameters
        ----------
        text:
            Natural-language assertion to analyse.
        assertion_id:
            Identifier for the assertion being analysed.
        context_facts:
            Optional existing facts that can refine interpretation confidences.
        """
        start = time.perf_counter()
        ambiguities = self._match_patterns(text, context_facts=context_facts)
        severity = _max_severity([a.severity for a in ambiguities])
        needs_clarification = _requires_clarification(ambiguities)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return AmbiguityReport(
            assertion_id=assertion_id,
            detected_ambiguities=tuple(ambiguities),
            severity=severity,
            needs_clarification=needs_clarification,
            detection_method="datalog_rules",
            processing_time_ms=elapsed_ms,
        )

    def _match_patterns(
        self,
        text: str,
        *,
        context_facts: tuple[str, ...],
    ) -> list[Ambiguity]:
        ambiguities: list[Ambiguity] = []
        for pattern, phrase in self.library.match(text):
            interpretations = self._refine_interpretations(
                pattern.interpretations,
                text,
                context_facts,
            )
            ambiguities.append(
                Ambiguity(
                    phrase=phrase,
                    kind=pattern.category,
                    severity=pattern.severity,
                    candidate_interpretations=interpretations,
                    resolved=False,
                    resolution_method=None,
                )
            )
        return ambiguities

    def _refine_interpretations(
        self,
        interpretations: tuple[Interpretation, ...],
        text: str,
        context_facts: tuple[str, ...],
    ) -> tuple[Interpretation, ...]:
        """Adjust interpretation confidences based on context clues.

        For example, if the text mentions driving, boost the ``driving``
        distance interpretation.  The returned tuple preserves order and
        re-normalises confidences so they sum to 1.0.
        """
        adjusted: list[Interpretation] = []
        for interp in interpretations:
            confidence = interp.base_confidence
            if interp.code == "driving" and (
                "开车" in text or "驾车" in text or "drive" in text.lower()
            ):
                confidence = 0.70
            elif interp.code == "self_service" and "自助" in text:
                confidence = 0.80
            elif interp.code == "staff_service" and "代洗" in text:
                confidence = 0.95
            elif interp.code == "automatic" and "自动" in text:
                confidence = 0.90
            adjusted.append(
                Interpretation(
                    code=interp.code,
                    formalization=interp.formalization,
                    base_confidence=confidence,
                )
            )

        total = sum(i.base_confidence for i in adjusted)
        if total > 0:
            normalized = tuple(
                Interpretation(
                    code=i.code,
                    formalization=i.formalization,
                    base_confidence=round(i.base_confidence / total, 4),
                )
                for i in adjusted
            )
        else:
            normalized = tuple(adjusted)
        return normalized


__all__ = ["AmbiguityDetector"]
