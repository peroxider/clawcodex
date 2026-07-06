"""Ambiguity detector for natural-language assertions.

The detector consumes a pattern library (by default the built-in F-134 / F-148
library) and produces an AmbiguityReport.  It intentionally does not call
external solvers; the matching logic is a direct Python translation of the
Datalog pattern rules described in the LKB v3 spec.

F-148 removes all scenario-bound interpretations and refinement rules from
the default library.  The default ``P-DIST-001`` is a matcher-only shell;
downstream callers attach their own modalities (e.g. on_foot /
straight_line / by_vehicle for a generic consumer, or TruckDistance /
AirDistance for a logistics consumer) by registering a `P-DIST-001` clone
through ``FuzzyPatternLibrary.add(...)``.  The same applies to refinement
rules: the previously hard-coded ``driving_keyword_distance`` boost is now
the downstream consumer's concern (via per-``FuzzyPattern
refinement_rules=...``), not a kernel namespace.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Callable, get_args

from .fuzzy_types import (
    Ambiguity,
    AmbiguityKind,
    AmbiguityReport,
    DetectionMethod,
    Interpretation,
    Severity,
)

if TYPE_CHECKING:
    from .audit import AuditLog
    from .fuzzy_patterns import FuzzyPattern, FuzzyPatternLibrary, RefinementRule


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

    def __init__(
        self,
        library: "FuzzyPatternLibrary | None" = None,
        *,
        llm_fallback_provider: Any = None,
        audit_log: "AuditLog | None" = None,
        refinement_rules: tuple["RefinementRule", ...] | None = None,
    ) -> None:
        from .fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY

        self.library = library or BUILT_IN_PATTERN_LIBRARY
        self.llm_fallback_provider = llm_fallback_provider
        self.audit_log = audit_log
        # F-148: the detector has no default refinement rule set.
        # Scenario-specific refinements (e.g. driving-keyword boost) are
        # supplied by downstream consumers via per-pattern
        # `FuzzyPattern.refinement_rules` fields, or via this constructor
        # argument when an application-level rule set is appropriate.
        self.refinement_rules: tuple[Callable[..., Any], ...] = (
            refinement_rules if refinement_rules is not None else ()
        )

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
        detection_method: "DetectionMethod" = "datalog_rules"
        if not ambiguities and self.llm_fallback_provider is not None:
            from .flags import is_llm_facts_enabled

            if is_llm_facts_enabled():
                llm_ambiguity = self._llm_fallback(text, assertion_id, context_facts)
                if llm_ambiguity is not None:
                    ambiguities = [llm_ambiguity]
                    detection_method = "llm_fallback"
        severity = _max_severity([a.severity for a in ambiguities])
        needs_clarification = _requires_clarification(ambiguities)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return AmbiguityReport(
            assertion_id=assertion_id,
            detected_ambiguities=tuple(ambiguities),
            severity=severity,
            needs_clarification=needs_clarification,
            detection_method=detection_method,
            processing_time_ms=elapsed_ms,
        )

    def _llm_fallback(
        self,
        text: str,
        assertion_id: str,
        context_facts: tuple[str, ...],
    ) -> Ambiguity | None:
        """Use the LLM to classify an un-matched phrase into a known ambiguity kind.

        Hard-capped at one LLM call per ``detect()`` invocation.  Free-form
        kinds are rejected; interpretation codes must belong to the pattern
        library's own enum for the matched kind.
        """
        if self.llm_fallback_provider is None:
            return None

        kind_to_codes = self._kind_code_map()
        valid_kinds = sorted(get_args(AmbiguityKind))
        prompt = self._build_llm_fallback_prompt(text, valid_kinds, kind_to_codes)
        try:
            from clawcodex_ext.providers.base import ChatMessage

            response = self.llm_fallback_provider.chat(
                [ChatMessage(role="user", content=prompt)]
            )
            raw = response.content
            model_id = getattr(response, "model", "unknown") or "unknown"
        except Exception as exc:  # noqa: BLE001 - fallback must not break detection
            return None

        parsed = self._parse_llm_fallback_response(raw)
        if parsed is None:
            return None
        kind = parsed.get("kind")
        if kind not in valid_kinds:
            raise ValueError(f"LLM fallback returned unknown ambiguity kind: {kind}")
        allowed_codes = kind_to_codes.get(kind, frozenset())
        interpretations: list[Interpretation] = []
        for interp in parsed.get("interpretations", ()):
            code = interp.get("code")
            if code not in allowed_codes:
                continue
            confidence = max(0.0, min(1.0, float(interp.get("confidence", 0.0))))
            if confidence < 0.30:
                continue
            interpretations.append(
                Interpretation(
                    code=code,
                    formalization=str(interp.get("formalization", "")),
                    base_confidence=confidence,
                )
            )
        if not interpretations:
            return None

        from .audit import (
            append_event_once,
            event_for_llm_fallback_used,
        )
        from .metrics import record_llm_fallback_used

        if self.audit_log is not None:
            append_event_once(
                self.audit_log,
                event_for_llm_fallback_used(
                    phrase=text[:120],
                    kind=kind,
                    candidate_count=len(interpretations),
                    model_id=model_id,
                ),
                event_type="lkb_llm_fallback_used",
            )
        record_llm_fallback_used(phrase=text[:120], kind=kind)

        return Ambiguity(
            phrase=text[:120],
            kind=kind,
            severity="major",
            candidate_interpretations=tuple(interpretations),
            resolved=False,
            resolution_method=None,
        )

    def _kind_code_map(self) -> dict[str, frozenset[str]]:
        """Return the set of interpretation codes defined for each AmbiguityKind."""
        mapping: dict[str, set[str]] = {}
        for pattern in self.library.patterns:
            codes = mapping.setdefault(pattern.category, set())
            for interpretation in pattern.interpretations:
                codes.add(interpretation.code)
        return {kind: frozenset(codes) for kind, codes in mapping.items()}

    def _build_llm_fallback_prompt(
        self,
        text: str,
        valid_kinds: list[str],
        kind_to_codes: dict[str, frozenset[str]],
    ) -> str:
        code_listing = "\n".join(
            f"  {kind}: {sorted(codes)}"
            for kind, codes in sorted(kind_to_codes.items())
        )
        return (
            "You are an ambiguity classifier for a logical kanban system. "
            "Given the user phrase, classify it into exactly one of the "
            f"allowed kinds: {valid_kinds}.\n"
            "Return strictly JSON with shape:\n"
            '{"kind": "semantic_vagueness", "interpretations": [{"code": "option_a", '
            '"formalization": "Estimate({entity}, {value})", "confidence": 0.6}]}\n'
            "Interpretation codes must be drawn from the allowed set for that kind:\n"
            f"{code_listing}\n"
            f"Phrase: {text}\n"
            "JSON:"
        )

    def _parse_llm_fallback_response(self, raw: str) -> dict[str, Any] | None:
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        interpretations = parsed.get("interpretations")
        if not isinstance(interpretations, list):
            return None
        normalized_interpretations = []
        for interp in interpretations:
            if isinstance(interp, dict):
                normalized_interpretations.append(interp)
        return {
            "kind": parsed.get("kind"),
            "interpretations": normalized_interpretations,
        }

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
                pattern=pattern,
            )
            ambiguities.append(
                Ambiguity(
                    phrase=phrase,
                    kind=pattern.category,
                    severity=pattern.severity,
                    candidate_interpretations=interpretations,
                    resolved=False,
                    resolution_method=None,
                    pattern_id=pattern.pattern_id,
                    clarification_prompt=pattern.clarification_prompt,
                )
            )
        return ambiguities

    def _refine_interpretations(
        self,
        interpretations: tuple[Interpretation, ...],
        text: str,
        context_facts: tuple[str, ...],
        *,
        pattern: "FuzzyPattern | None" = None,
    ) -> tuple[Interpretation, ...]:
        """Adjust interpretation confidences based on context clues.

        The detector walks two rule sources in order:

        1. The detector-level ``self.refinement_rules`` (default empty as
           of F-148; downstream callers opt in via the constructor).
        2. The pattern-level ``pattern.refinement_rules`` (F-148 PR 1
           addition — empty by default; downstream callers opt in).

        Each rule is ``Callable[[str, Interpretation], Interpretation]``:
        it returns an adjusted ``Interpretation`` whose ``base_confidence``
        reflects the textual context, or the original ``Interpretation``
        unchanged if the rule does not apply.

        The returned tuple preserves order and re-normalises confidences so
        they sum to 1.0.
        """
        rules: tuple[Callable[..., Any], ...] = self.refinement_rules
        if pattern is not None:
            rules = (*rules, *pattern.refinement_rules)
        adjusted: list[Interpretation] = []
        for interp in interpretations:
            refined = interp
            for rule in rules:
                refined = rule(text, refined)
            adjusted.append(refined)

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
