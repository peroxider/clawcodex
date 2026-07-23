"""Predicate extraction and glossary validation for Canonical IR.

Walks a CanonicalAssertion body, collects every predicate name, and validates
that each name is registered in the glossary.  Unknown predicates put the
assertion into ``needs_glossary_review``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .glossary import Glossary
from .ir import IROperation, IRPredicate, CanonicalAssertion, IRNode

@dataclass(frozen=True, slots=True)
class PredicateExtraction:
    """Result of extracting predicates from a CanonicalAssertion."""

    predicates: frozenset[str] = field(default_factory=frozenset)
    unknown: frozenset[str] = field(default_factory=frozenset)
    status: Literal["valid", "needs_glossary_review"] = "valid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicates": sorted(self.predicates),
            "unknown": sorted(self.unknown),
            "status": self.status,
        }

def extract_predicates(node: IRNode) -> frozenset[str]:
    """Recursively collect predicate names from an IR node."""
    if isinstance(node, IRPredicate):
        return frozenset([node.pred])
    if isinstance(node, IROperation):
        found: set[str] = set()
        for child in node.args:
            found.update(extract_predicates(child))
        return frozenset(found)
    raise TypeError(f"Unsupported IR node type: {type(node).__name__}")

def validate_assertion(
    assertion: CanonicalAssertion,
    glossary: Glossary,
) -> PredicateExtraction:
    """Validate all predicates in ``assertion`` against ``glossary``.

    Returns a ``PredicateExtraction`` whose ``status`` is
    ``needs_glossary_review`` when any predicate is not registered.
    """
    predicates = extract_predicates(assertion.body)
    unknown = predicates - glossary.predicate_names()
    status: Literal["valid", "needs_glossary_review"] = (
        "needs_glossary_review" if unknown else "valid"
    )
    return PredicateExtraction(
        predicates=predicates,
        unknown=unknown,
        status=status,
    )

__all__ = [
    "PredicateExtraction",
    "extract_predicates",
    "validate_assertion",
]
