"""Prompt-integrated method reuse for TaskDecomposer (F-151).

Compresses the engineering :class:`EngineeringMethod` library into an
LLM-friendly summary block that fits inside the system prompt. The
summary is included verbatim by :class:`TaskDecomposer` so the LLM
*sees* the available decomposition templates and can carry a
``method_ref`` pointer in :class:`ProposedTask.lkbMetadata`.

Design notes
------------
* ``summarize_methods`` enforces a hard token budget — over-budget
  methods are dropped (lowest score first) instead of being
  truncated mid-line, so the summary never injects broken metadata.
* ``select_methods_by_pattern`` uses lightweight substring +
  Levenshtein-distance scoring.  It is deterministic and
  dependency-free (no regex compilation per call).
* The summary uses the canonical ``[M-id] Pattern: ...`` line shape
  described in ``f-151-method-prompt-injection.md``.  Adjusting the
  shape is intentionally a one-line change here — every consumer
  reads via :func:`summarize_methods`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .method_library import EngineeringMethod, METHOD_LIBRARY

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` using a 4-char heuristic.

    The heuristic is intentionally simple and dependency-free: 1 token
    is approximately 4 characters of English text.  Tests assert that
    the *summary* is under a 2 000-token budget; the estimation here
    errs on the conservative (slightly over-estimating) side so the
    assertion never under-counts.
    """
    if not text:
        return 0
    # 1 token ≈ 4 chars.  Round up to never under-count short strings.
    return max(1, (len(text) + 3) // 4)

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return text.lower().strip()

def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance between ``a`` and ``b``.

    The implementation is the textbook O(len(a) * len(b)) DP variant
    with a row-reduced memory footprint. Inputs are expected to be
    short (≤ a few dozen characters) so we don't need a more advanced
    algorithm.  The function is dependency-free.
    """
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
            curr[j] = min(
                curr[j - 1] + 1,  # insertion
                prev[j] + 1,  # deletion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]

def score_method(
    method: EngineeringMethod,
    goal: str,
) -> float:
    """Return a relevance score for ``method`` against ``goal``.

    The score is the sum of:
    * 1.0 for each token in ``goal`` that appears as a substring in
      the method's pattern or description.
    * 0.5 for each Levenshtein-1 fuzzy match against the pattern.
    * 0.2 for each tag match.
    The score is non-negative; zero means no signal.
    """
    goal_norm = _normalise(goal)
    if not goal_norm:
        return 0.0
    pattern = _normalise(method.pattern)
    description = _normalise(method.description)
    tag_blob = " ".join(_normalise(tag) for tag in method.tags)

    score = 0.0
    # Token-level substring matching — split on whitespace and
    # non-alphanumerics so "add-middleware" still matches "add".
    tokens: list[str] = []
    current: list[str] = []
    for ch in goal_norm:
        if ch.isalnum():
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))

    for token in tokens:
        if not token:
            continue
        if token in pattern or token in description or token in tag_blob:
            score += 1.0
            continue
        # Fuzzy fallback: compare against the pattern tokens.
        for pattern_token in pattern.replace("_", " ").replace("-", " ").split():
            if not pattern_token:
                continue
            if _levenshtein(token, pattern_token) <= 1:
                score += 0.5
                break
    return score

# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def select_methods_by_pattern(
    goal: str,
    library: tuple[EngineeringMethod, ...] = METHOD_LIBRARY,
    *,
    top_k: int = 10,
) -> tuple[EngineeringMethod, ...]:
    """Return up to ``top_k`` methods most relevant to ``goal``.

    Methods are sorted by descending :func:`score_method` and
    deterministically tie-broken on ``(pattern, method_id)`` so the
    output is stable across Python invocations.

    An empty ``goal`` returns an empty selection — we do not score
    against an empty query.  Negative ``top_k`` values are clamped to
    zero.
    """
    if not goal or top_k <= 0:
        return ()

    scored: list[tuple[float, str, str, EngineeringMethod]] = []
    for method in library:
        score = score_method(method, goal)
        if score <= 0:
            continue
        scored.append((score, method.pattern, method.method_id, method))

    scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return tuple(entry[3] for entry in scored[:top_k])

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MethodSummaryResult:
    """Result of :func:`summarize_methods` — the rendered text plus metadata.

    Attributes
    ----------
    text:
        The summary body (no leading ``## `` header — the caller
        decides how to wrap it).
    included_method_ids:
        The method_ids that were rendered, in the order they appear in
        ``text``.  Useful for downstream logging / audit events.
    dropped_method_ids:
        The method_ids that were skipped to stay under the token
        budget, in the order they were considered.  May be empty.
    estimated_tokens:
        The estimated token count of ``text`` (see :func:`estimate_tokens`).
    """

    text: str
    included_method_ids: tuple[str, ...]
    dropped_method_ids: tuple[str, ...]
    estimated_tokens: int

def _method_line(method: EngineeringMethod) -> str:
    """Render a single ``[M-id] Pattern: ...`` summary line for ``method``."""
    description = method.description.strip()
    if not description:
        description = "No description."

    # Sub-task role sequence, e.g. "design → impl → test".
    roles = method.roles()
    role_sequence = " → ".join(roles) if roles else "—"

    assumptions = "none"
    if method.assumptions:
        # Cap assumption snippet length so a single method can't
        # dominate the budget by listing many long assumptions.
        snippets = []
        for assumption in method.assumptions[:2]:
            snippet = assumption.strip()
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            snippets.append(snippet)
        assumptions = ", ".join(snippets)

    return (
        f"- [{method.method_id}] {method.pattern}: "
        f"{description}  "
        f"Subtasks: {role_sequence}.  "
        f"Assumes: {assumptions}."
    )

def _iter_scored(
    methods: Iterable[EngineeringMethod],
    goal: str,
) -> list[tuple[float, str, str, EngineeringMethod]]:
    """Return methods ordered by relevance to ``goal``.

    The list is sorted by ``(-score, pattern, method_id)`` so a method
    with score 0 (no signal) still gets a deterministic position.
    """
    scored: list[tuple[float, str, str, EngineeringMethod]] = []
    for method in methods:
        score = score_method(method, goal)
        scored.append((score, method.pattern, method.method_id, method))
    scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return scored

def summarize_methods(
    methods: tuple[EngineeringMethod, ...] | Iterable[EngineeringMethod] = METHOD_LIBRARY,
    *,
    goal: str = "",
    max_tokens: int = 1800,
    header: str = ("## Engineering Methods (use these templates when applicable)"),
) -> MethodSummaryResult:
    """Render ``methods`` as a compact, budget-bounded summary block.

    Parameters
    ----------
    methods:
        The library to summarize.  An iterable is accepted so callers
        can pass the output of :func:`select_methods_by_pattern`
        directly.  Default is :data:`METHOD_LIBRARY`.
    goal:
        Optional goal string used to rank methods by relevance.  When
        empty, methods appear in their library order.  When non-empty,
        higher-scoring methods are rendered first so a budget cut
        retains the most relevant entries.
    max_tokens:
        Hard token budget for the rendered summary.  Methods that
        would push the summary over the budget are dropped (not
        truncated).  Defaults to 1 800 — a comfortable margin below
        the 2 000-token cap stated in the F-151 spec.
    header:
        The leading ``## `` line.  Customize for locale / branding.
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    materialised: tuple[EngineeringMethod, ...]
    if isinstance(methods, tuple):
        materialised = methods
    else:
        materialised = tuple(methods)

    if not materialised:
        return MethodSummaryResult(
            text="",
            included_method_ids=(),
            dropped_method_ids=(),
            estimated_tokens=0,
        )

    # Sort by relevance when a goal is given; otherwise keep input order.
    if goal:
        ordered = [entry[3] for entry in _iter_scored(materialised, goal)]
    else:
        ordered = list(materialised)

    header_text = f"{header}\n" if header else ""
    header_tokens = estimate_tokens(header_text)
    budget = max_tokens - header_tokens
    if budget <= 0:
        # Header alone exhausts the budget.  Return just the header so
        # callers can still see *something* — but no methods.
        return MethodSummaryResult(
            text=header_text,
            included_method_ids=(),
            dropped_method_ids=tuple(m.method_id for m in ordered),
            estimated_tokens=header_tokens,
        )

    included_ids: list[str] = []
    dropped_ids: list[str] = []
    lines: list[str] = []
    current_tokens = 0
    for method in ordered:
        line = _method_line(method)
        line_tokens = estimate_tokens(line)
        # Reserve 1 token for the trailing newline so the final line
        # doesn't accidentally exceed the budget.
        if current_tokens + line_tokens + 1 > budget:
            dropped_ids.append(method.method_id)
            continue
        lines.append(line)
        included_ids.append(method.method_id)
        current_tokens += line_tokens + 1

    body = "\n".join(lines)
    full_text = f"{header_text}{body}" if body else header_text.rstrip("\n")
    return MethodSummaryResult(
        text=full_text,
        included_method_ids=tuple(included_ids),
        dropped_method_ids=tuple(dropped_ids),
        estimated_tokens=estimate_tokens(full_text),
    )

__all__ = [
    "MethodSummaryResult",
    "estimate_tokens",
    "score_method",
    "select_methods_by_pattern",
    "summarize_methods",
]
