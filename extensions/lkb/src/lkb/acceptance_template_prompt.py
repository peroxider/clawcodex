"""Prompt helpers for top-level acceptance templates (F-155)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .acceptance_template import AcceptanceTemplate, get_all_acceptance_templates
from .method_prompt import estimate_tokens

@dataclass(frozen=True)
class AcceptanceTemplateSummaryResult:
    text: str
    included_template_ids: tuple[str, ...]
    dropped_template_ids: tuple[str, ...]
    estimated_tokens: int

def _normalise(text: str) -> str:
    return text.lower().strip()

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]

def score_acceptance_template(template: AcceptanceTemplate, goal: str) -> float:
    goal_norm = _normalise(goal)
    if not goal_norm:
        return 0.0
    haystack = _normalise(
        " ".join(
            (
                template.template_id.replace("-", " "),
                template.description,
                template.assertion_template,
                " ".join(template.applies_to_roles),
            )
        )
    )
    score = 0.0
    tokens = [token for token in _split_tokens(goal_norm) if token]
    hay_tokens = haystack.replace("_", " ").replace("-", " ").split()
    for token in tokens:
        if token in haystack:
            score += 1.0
            continue
        if any(_levenshtein(token, candidate) <= 1 for candidate in hay_tokens):
            score += 0.5
    return score

def select_templates_by_goal(
    goal: str,
    registry: Iterable[AcceptanceTemplate] | None = None,
    *,
    top_k: int = 8,
) -> tuple[AcceptanceTemplate, ...]:
    if not goal or top_k <= 0:
        return ()
    templates = tuple(registry if registry is not None else get_all_acceptance_templates())
    scored: list[tuple[float, str, AcceptanceTemplate]] = []
    for template in templates:
        if template.status != "approved":
            continue
        score = score_acceptance_template(template, goal)
        if score <= 0:
            continue
        scored.append((score, template.template_id, template))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return tuple(entry[2] for entry in scored[:top_k])

def summarize_acceptance_templates(
    templates: Iterable[AcceptanceTemplate],
    *,
    max_tokens: int = 800,
    header: str = "## Acceptance Templates (prefer these for assertions/proofs)",
) -> AcceptanceTemplateSummaryResult:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    materialised = tuple(templates)
    if not materialised:
        return AcceptanceTemplateSummaryResult("", (), (), 0)

    header_text = f"{header}\n" if header else ""
    budget = max_tokens - estimate_tokens(header_text)
    if budget <= 0:
        return AcceptanceTemplateSummaryResult(
            header_text.rstrip("\n"),
            (),
            tuple(template.template_id for template in materialised),
            estimate_tokens(header_text),
        )

    lines: list[str] = []
    included: list[str] = []
    dropped: list[str] = []
    current_tokens = 0
    for template in materialised:
        roles = ",".join(template.applies_to_roles) if template.applies_to_roles else "any"
        line = (
            f"- [{template.template_id}] roles={roles}; "
            f"assertion={template.assertion_template}; proof={template.proof_template or 'optional'}"
        )
        line_tokens = estimate_tokens(line) + 1
        if current_tokens + line_tokens > budget:
            dropped.append(template.template_id)
            continue
        lines.append(line)
        included.append(template.template_id)
        current_tokens += line_tokens

    text = f"{header_text}{chr(10).join(lines)}" if lines else header_text.rstrip("\n")
    return AcceptanceTemplateSummaryResult(
        text=text,
        included_template_ids=tuple(included),
        dropped_template_ids=tuple(dropped),
        estimated_tokens=estimate_tokens(text),
    )

def _split_tokens(text: str) -> tuple[str, ...]:
    out: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isalnum():
            current.append(ch)
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return tuple(out)

__all__ = [
    "AcceptanceTemplateSummaryResult",
    "score_acceptance_template",
    "select_templates_by_goal",
    "summarize_acceptance_templates",
]
