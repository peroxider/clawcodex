"""Natural-language renderer for Canonical IR and proof traces.

Explanations are produced from the IR structure and the glossary, never from
arbitrary text embedded in the assertion.  This keeps translations constrained
to the glossary vocabulary.
"""

from __future__ import annotations

from typing import Any

from .glossary import Glossary
from .ir import IROperation, IRPredicate, CanonicalAssertion, IRNode

def render_node(node: IRNode, glossary: Glossary | None = None) -> str:
    """Render a single IR node as a human-readable sentence fragment."""
    if isinstance(node, IRPredicate):
        return _render_predicate(node, glossary)
    if isinstance(node, IROperation):
        return _render_operation(node, glossary)
    raise TypeError(f"Unsupported IR node type: {type(node).__name__}")

def render_assertion(assertion: CanonicalAssertion, glossary: Glossary | None = None) -> str:
    """Render a full CanonicalAssertion as a sentence."""
    quantifier_text = _render_quantifier(assertion.quantifier, assertion.vars)
    body_text = render_node(assertion.body, glossary)
    return f"{quantifier_text}, {body_text}."

def render_proof_trace(
    proof_trace: dict[str, Any] | tuple[dict[str, Any], ...] | list[dict[str, Any]],
    glossary: Glossary | None = None,
) -> str:
    """Render a proof-trace entry or sequence as a concise explanation."""
    if isinstance(proof_trace, dict):
        rule = proof_trace.get("rule", "unknown")
        premises = proof_trace.get("premises", [])
        conclusion = proof_trace.get("conclusion", "")
        premises_text = ", ".join(str(p) for p in premises) if premises else "given"
        return f"By rule {rule}: from {premises_text} conclude {conclusion}."

    parts: list[str] = []
    for entry in proof_trace:
        parts.append(render_proof_trace(entry, glossary))
    return " ".join(parts)

def _render_predicate(node: IRPredicate, glossary: Glossary | None) -> str:
    args_text = ", ".join(str(a) for a in node.args)
    entry = glossary.resolve(node.pred) if glossary is not None else None
    name = entry.name if entry is not None else node.pred
    if not node.args:
        return f"{name} holds"
    return f"{name}({args_text})"

def _render_operation(node: IROperation, glossary: Glossary | None) -> str:
    op = node.op
    args = node.args
    if op == "implies" and len(args) == 2:
        antecedent = render_node(args[0], glossary)
        consequent = render_node(args[1], glossary)
        return f"if {antecedent} then {consequent}"
    if op == "and":
        parts = [render_node(a, glossary) for a in args]
        if not parts:
            return "true"
        if len(parts) == 1:
            return parts[0]
        return " and ".join(parts)
    if op == "or":
        parts = [render_node(a, glossary) for a in args]
        if not parts:
            return "false"
        if len(parts) == 1:
            return parts[0]
        return " or ".join(parts)
    if op == "not" and len(args) == 1:
        return f"it is not the case that {render_node(args[0], glossary)}"
    rendered = [render_node(a, glossary) for a in args]
    return f"{op}({', '.join(rendered)})"

def _render_quantifier(
    quantifier: str,
    vars: tuple[Any, ...],
) -> str:
    if not vars:
        mapping = {
            "forall": "For all cases",
            "exists": "There exists a case",
            "unique": "There exists exactly one case",
        }
        return mapping.get(quantifier, f"For {quantifier}")

    var_texts = [f"{v.name}:{v.type}" for v in vars]
    var_list = ", ".join(var_texts)
    mapping = {
        "forall": f"For all {var_list}",
        "exists": f"There exists {var_list}",
        "unique": f"There exists exactly one {var_list}",
    }
    return mapping.get(quantifier, f"{quantifier} {var_list}")

__all__ = [
    "render_assertion",
    "render_node",
    "render_proof_trace",
]
