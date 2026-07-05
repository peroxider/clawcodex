"""Pattern library for fuzzy ambiguity detection.

This module provides a lightweight, regex-based pattern registry that mirrors
the Datalog pattern library described in the LKB v3 spec (section 9.4.1).
External solvers such as clingo or Soufflé are intentionally not used; the
registry is pure Python so it integrates cleanly with the Layer1 engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .fuzzy_types import AmbiguityKind, Interpretation, Severity


@dataclass(frozen=True, slots=True)
class FuzzyPattern:
    """A single ambiguity pattern entry."""

    pattern_id: str
    category: AmbiguityKind
    severity: Severity
    matcher: Callable[[str], bool]
    interpretations: tuple[Interpretation, ...]
    clarification_prompt: str = ""

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
    """Best-effort extraction of the ambiguous phrase from the text."""
    # Try to capture the first number+meter expression for distance patterns.
    if "距离" in pattern.pattern_id.lower() or "dist" in pattern.pattern_id.lower():
        m = re.search(r"(离家|距离)?\s*\d+\s*[米公里m]", text)
        if m:
            return m.group(0)
    if "serv" in pattern.pattern_id.lower() or "洗车" in text:
        m = re.search(r"洗[车东西]", text)
        if m:
            return m.group(0)
    if "depdir" in pattern.pattern_id.lower():
        for token in ("依赖", "有关", "相关"):
            if token in text:
                return token
    if "temp" in pattern.pattern_id.lower():
        for token in ("很快", "马上", "不久", "立马", "立刻"):
            if token in text:
                return token
    if "info" in pattern.pattern_id.lower():
        for token in ("去", "到"):
            if token in text:
                return token
    if "accept" in pattern.pattern_id.lower():
        for token in ("完成", "done", "做完"):
            if token in text:
                return token
    return text[:60]


def _default_library() -> FuzzyPatternLibrary:
    """Return the built-in pattern library used by F-134."""
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
                    code="walking",
                    formalization="WalkingDistance({from}, {to}, {number})",
                    base_confidence=0.60,
                ),
                Interpretation(
                    code="straight_line",
                    formalization="EuclideanDistance({from}, {to}, {number})",
                    base_confidence=0.40,
                ),
                Interpretation(
                    code="driving",
                    formalization="DrivingDistance({from}, {to}, {number})",
                    base_confidence=0.00,
                ),
            ),
            clarification_prompt="您说的距离是指步行距离、直线距离还是驾车距离？",
        )
    )

    # P-SERV-001: service subject ambiguity (car wash example)
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-SERV-001",
            category="semantic_vagueness",
            severity="critical",
            matcher=lambda t: "洗车" in t
            and "自助" not in t
            and "代洗" not in t
            and "自动" not in t,
            interpretations=(
                Interpretation(
                    code="staff_service",
                    formalization="StaffServiceWash({staff}, {vehicle})",
                    base_confidence=0.80,
                ),
                Interpretation(
                    code="self_service",
                    formalization="SelfServiceWash({customer}, {vehicle})",
                    base_confidence=0.15,
                ),
                Interpretation(
                    code="automatic",
                    formalization="AutomaticWash({vehicle})",
                    base_confidence=0.05,
                ),
            ),
            clarification_prompt="您说的洗车是人工代洗、自助洗车还是自动洗车？",
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

    # P-INFO-001: missing location / subject information
    lib = lib.add(
        FuzzyPattern(
            pattern_id="P-INFO-001",
            category="missing_subject",
            severity="major",
            matcher=lambda t: bool(
                re.search(r"去[洗修买吃]", t) and not re.search(r"从|在", t)
            ),
            interpretations=(
                Interpretation(
                    code="vehicle_at_home",
                    formalization="At({vehicle}, user_home)",
                    base_confidence=0.95,
                ),
                Interpretation(
                    code="vehicle_unknown",
                    formalization="At({vehicle}, unknown_location)",
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

    # Domain constraints: prune interpretation combinations that are inconsistent.
    lib = lib.add_constraint(
        DomainConstraint(
            blocks=frozenset({"self_service", "straight_line"}),
            rationale="Self-service car wash usually implies the customer walks to the bay.",
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
