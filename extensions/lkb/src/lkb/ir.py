"""Canonical Assertion IR for Logical Kanban.

The CanonicalAssertion dataclass is the single source of truth for logical
assertions.  Presentation formatting, natural-language text, and solver
compilation targets are derived from this IR rather than stored alongside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1.0"

AssertionRole = Literal["axiom", "derived", "assumption"]
AssertionKind = Literal[
    "prerequisite",
    "state_transition",
    "acceptance",
    "consistency",
    "invariant",
]
Quantifier = Literal["forall", "exists", "unique"]

@dataclass(frozen=True, slots=True)
class IRVariable:
    """A typed variable bound by the assertion quantifier."""

    name: str
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type}

@dataclass(frozen=True, slots=True)
class IRPredicate:
    """Atomic predicate application: Pred(args...)."""

    pred: str
    args: tuple[str | int | float | bool, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"pred": self.pred, "args": list(self.args)}

@dataclass(frozen=True, slots=True)
class IROperation:
    """Compound boolean/logical operation over IR nodes."""

    op: str
    args: tuple["IRNode", ...]

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "args": [_node_to_dict(a) for a in self.args]}

IRNode = IRPredicate | IROperation

def _node_to_dict(node: IRNode) -> dict[str, Any]:
    return node.to_dict()

@dataclass(frozen=True, slots=True)
class CanonicalAssertion:
    """Normalized, presentation-independent logical assertion.

    The body may be either a single predicate application or a compound
    operation (implies, and, or, not, etc.).  No natural-language text is
    stored here; explanations are rendered from the IR and the proof trace.
    """

    role: AssertionRole
    kind: AssertionKind
    body: IRNode
    quantifier: Quantifier = "forall"
    vars: tuple[IRVariable, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "kind": self.kind,
            "quantifier": self.quantifier,
            "vars": [v.to_dict() for v in self.vars],
            "body": _node_to_dict(self.body),
        }

def make_canonical(
    *,
    role: AssertionRole,
    kind: AssertionKind,
    body: IRNode,
    quantifier: Quantifier = "forall",
    vars: tuple[IRVariable, ...]
    | list[IRVariable]
    | tuple[dict[str, str], ...]
    | list[dict[str, str]] = (),
    schema_version: str = SCHEMA_VERSION,
) -> CanonicalAssertion:
    """Convenience factory that normalizes variable collections to tuples."""
    normalized_vars: list[IRVariable] = []
    for item in vars:
        if isinstance(item, IRVariable):
            normalized_vars.append(item)
        elif isinstance(item, dict):
            normalized_vars.append(IRVariable(name=item["name"], type=item["type"]))
        else:
            raise TypeError(f"Expected IRVariable or dict, got {type(item).__name__}")
    return CanonicalAssertion(
        role=role,
        kind=kind,
        body=body,
        quantifier=quantifier,
        vars=tuple(normalized_vars),
        schema_version=schema_version,
    )

def pred(name: str, *args: str | int | float | bool) -> IRPredicate:
    """Shorthand for building an atomic predicate node."""
    return IRPredicate(pred=name, args=args)

def implies(left: IRNode, right: IRNode) -> IROperation:
    """Shorthand for building a material-implication node."""
    return IROperation(op="implies", args=(left, right))

def and_(*args: IRNode) -> IROperation:
    return IROperation(op="and", args=args)

def or_(*args: IRNode) -> IROperation:
    return IROperation(op="or", args=args)

def not_(node: IRNode) -> IROperation:
    return IROperation(op="not", args=(node,))

__all__ = [
    "AssertionKind",
    "AssertionRole",
    "CanonicalAssertion",
    "IROperation",
    "IRPredicate",
    "IRNode",
    "IRVariable",
    "Quantifier",
    "SCHEMA_VERSION",
    "and_",
    "implies",
    "make_canonical",
    "not_",
    "or_",
    "pred",
]
