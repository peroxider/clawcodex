"""Pattern library for fuzzy ambiguity detection.

This module provides a lightweight, regex-based pattern registry that mirrors
the Datalog pattern library described in the LKB v3 spec (section 9.4.1).
External solvers such as clingo or Soufflé are intentionally not used; the
registry is pure Python so it integrates cleanly with the Layer1 engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .fuzzy_types import AmbiguityKind, Interpretation, Severity


# A refinement rule converts one (text, interpretation) pair into a
# adjusted interpretation whose base_confidence reflects the textual
# context.  Detector-default rules live in
# ``ambiguity_detector.BuiltinRefinementRules``; ``FuzzyPattern`` may
# also declare its own.
RefinementRule = Callable[[str, Interpretation], Interpretation]


@dataclass(frozen=True, slots=True)
class FuzzyPattern:
    """A single ambiguity pattern entry."""

    pattern_id: str
    category: AmbiguityKind
    severity: Severity
    matcher: Callable[[str], bool]
    interpretations: tuple[Interpretation, ...]
    clarification_prompt: str = ""
    refinement_rules: tuple[RefinementRule, ...] = ()

    def matches(self, text: str) -> bool:
        return self.matcher(text)


@dataclass(frozen=True, slots=True)
class DomainConstraint:
    """A constraint that excludes an interpretation combination.

    The ``blocks`` field is a set of interpretation ``code`` values.  If every
    code in ``blocks`` is selected by the world generator, that world is
    pruned.
    """

    blocks: frozenset[str]
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class FuzzyPatternLibrary:
    """Immutable registry of ambiguity patterns and domain constraints."""

    patterns: tuple[FuzzyPattern, ...] = ()
    constraints: tuple[DomainConstraint, ...] = ()

    def add(self, pattern: FuzzyPattern) -> "FuzzyPatternLibrary":
        return FuzzyPatternLibrary(
            patterns=(*self.patterns, pattern),
            constraints=self.constraints,
        )

    def add_constraint(self, constraint: DomainConstraint) -> "FuzzyPatternLibrary":
        return FuzzyPatternLibrary(
            patterns=self.patterns,
            constraints=(*self.constraints, constraint),
        )

    def match(self, text: str) -> list[tuple[FuzzyPattern, str]]:
        """Return all matching patterns together with the matched phrase."""
        hits: list[tuple[FuzzyPattern, str]] = []
        for pattern in self.patterns:
            if pattern.matches(text):
                phrase = _extract_phrase(text, pattern)
                hits.append((pattern, phrase))
        return hits


def _has_any(text: str, *tokens: str) -> bool:
    return any(token in text for token in tokens)


def _extract_phrase(text: str, pattern: FuzzyPattern) -> str:
    """Best-effort extraction of the ambiguous phrase from the text.

    The default library ships only generic patterns, so a single
    text-prefix fallback is sufficient.  Patterns that need richer
    extraction should provide their own ``phrase_extractor`` callable
    (F-148 PR 1 de-scopes the legacy ``pattern_id`` substring router
    that previously branched on ``dist / serv / depdir / temp / info /
    accept`` tokens).
    """
    return text[:60]


def _default_library() -> FuzzyPatternLibrary:
    """Return the built-in pattern library used by F-134 / F-148.

    The library is intentionally domain-agnostic.  Scenario-specific
    patterns (car-wash, payment-method, deployment-strategy,
    file-format, ...) are supplied by downstream callers via
    ``FuzzyPatternLibrary.add(...)``.
    """
    lib = FuzzyPatternLibrary()

    # P-DIST-001: distance semantic vagueness
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-DIST-001",
            category="semantic_vagueness",
            severity="major",
            matcher=lambda t: bool(
                re.search(r"(离家|距离).*?\d+\s*[米公里m]", t)
                or re.search(r"\d+\s*[米公里m].*?(店|地方|位置)", t)
            ),
            interpretations=(
                Interpretation(
                    code="on_foot",
                    formalization="FootDistance({from}, {to}, {number})",
                    base_confidence=0.60,
                ),
                Interpretation(
                    code="straight_line",
                    formalization="EuclideanDistance({from}, {to}, {number})",
                    base_confidence=0.40,
                ),
                Interpretation(
                    code="by_vehicle",
                    formalization="VehicleDistance({from}, {to}, {number})",
                    base_confidence=0.00,
                ),
            ),
            clarification_prompt="您说的距离是指步行距离、直线距离还是驾车距离？",
        )
    )

    # P-PROX-001: proximity vagueness
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-PROX-001",
            category="semantic_vagueness",
            severity="minor",
            matcher=lambda t: bool(re.search(r"附近|旁边|周围|周边", t)),
            interpretations=(
                Interpretation(
                    code="very_close",
                    formalization="Distance < 100",
                    base_confidence=0.20,
                ),
                Interpretation(
                    code="close",
                    formalization="Distance < 500",
                    base_confidence=0.50,
                ),
                Interpretation(
                    code="moderate",
                    formalization="Distance < 2000",
                    base_confidence=0.30,
                ),
            ),
            clarification_prompt="您说的附近大概是多远的范围？",
        )
    )

    # P-TEMP-001: temporal vagueness
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-TEMP-001",
            category="temporal",
            severity="minor",
            matcher=lambda t: bool(re.search(r"很快|马上|不久|立马|立刻", t)),
            interpretations=(
                Interpretation(
                    code="immediate",
                    formalization="Duration < 5",
                    base_confidence=0.40,
                ),
                Interpretation(
                    code="soon",
                    formalization="Duration < 30",
                    base_confidence=0.45,
                ),
                Interpretation(
                    code="today",
                    formalization="SameDay",
                    base_confidence=0.15,
                ),
            ),
            clarification_prompt="您说的很快大概是什么时候？",
        )
    )

    # P-DEPDIR-001: unclear dependency direction
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-DEPDIR-001",
            category="unclear_dependency_direction",
            severity="critical",
            matcher=lambda t: bool(
                re.search(r"依赖|depends?\s+on|有关|相关|关联", t)
                and not re.search(r"(blockedBy|blocks|前置|阻塞|被阻塞)", t)
            ),
            interpretations=(
                Interpretation(
                    code="requires_first",
                    formalization="Requires({first}, {second})",
                    base_confidence=0.50,
                ),
                Interpretation(
                    code="requires_second",
                    formalization="Requires({second}, {first})",
                    base_confidence=0.50,
                ),
            ),
            clarification_prompt="请明确依赖方向：是 A 阻塞 B，还是 B 阻塞 A？",
        )
    )

    # P-INFO-001: missing subject / location information
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-INFO-001",
            category="missing_subject",
            severity="major",
            matcher=lambda t: bool(
                re.search(r"去(?:做|完成|办理)", t) and not re.search(r"从|在", t)
            ),
            interpretations=(
                Interpretation(
                    code="entity_default",
                    formalization="AtDefault({subject})",
                    base_confidence=0.95,
                ),
                Interpretation(
                    code="entity_unknown",
                    formalization="AtUnknownLocation({subject})",
                    base_confidence=0.05,
                ),
            ),
            clarification_prompt="您当前的位置是哪里？",
        )
    )

    # P-ACCEPT-001: acceptance criteria missing or vague
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-ACCEPT-001",
            category="acceptance_criteria",
            severity="major",
            matcher=lambda t: bool(
                re.search(r"完成|做完|done|finish", t)
                and not re.search(r"验收|证明|测试通过|test|acceptance", t)
            ),
            interpretations=(
                Interpretation(
                    code="needs_acceptance_proof",
                    formalization="NeedsAcceptanceProof({task})",
                    base_confidence=0.90,
                ),
                Interpretation(
                    code="implicit_acceptance",
                    formalization="ImplicitAcceptance({task})",
                    base_confidence=0.10,
                ),
            ),
            clarification_prompt="完成该任务需要什么验收标准或证明？",
        )
    )

    return lib


BUILT_IN_PATTERN_LIBRARY: FuzzyPatternLibrary = _default_library()


__all__ = [
    "BUILT_IN_PATTERN_LIBRARY",
    "DomainConstraint",
    "FuzzyPattern",
    "FuzzyPatternLibrary",
]
