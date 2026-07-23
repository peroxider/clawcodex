"""F-141 Causal Verification Layer (CAP-compatible).

This module implements an in-process, lightweight causal engine that mirrors
the Causal Agent Protocol (CAP) verb semantics without depending on the
upstream ``cap-example`` reference repository.  The implementation is
deliberately a *synthetic* graph derived from a :class:`FactsSnapshot`; it
does not run any learned SCM, and it does not perform Pearl-style
identifiability (back-door, front-door, IV) reasoning.

The engine exposes three CAP verbs:

* ``meta.capabilities`` — discover which verbs the engine supports.
* ``graph.neighbors`` — list parents / children / ancestors / descendants.
* ``intervene.do`` — estimate the standardised causal effect of a
  treatment on an outcome.
* ``observe.predict`` — return a baseline prediction for a node.

Causal weight thresholds (mirroring spec §10.6)::

    weight >= 0.7   → "significant"
    0.4 <= w < 0.7  → "moderate"  (advisory; needs human review)
    weight < 0.4    → "weak"      (advisory or strict-deny)

The engine is advisory by default.  When the ``LKB_STRICT_CAUSAL`` env
variable is set, a ``weak`` outcome is treated as a binding denial; the
:class:`LogicalKanbanService` is responsible for turning the advisory
result into the final commit decision.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .types import FactsSnapshot

CausalMechanism = Literal["direct", "indirect", "structural", "proof", "null"]
CausalTag = Literal["significant", "moderate", "weak"]
CausalScope = Literal["parents", "children", "ancestors", "descendants"]

CAP_VERBS: tuple[str, ...] = (
    "graph.neighbors",
    "intervene.do",
    "observe.predict",
)

# Threshold table (see spec §10.6)
SIGNIFICANT_THRESHOLD = 0.7
MODERATE_THRESHOLD = 0.4

# Maximum entries kept in the per-process causal result cache.  The cache is
# keyed by (snapshot_hash, edge_key, treatment, outcome); a 256-entry LRU is
# more than enough to make repeated F-137 in-memory validation runs hit
# single-digit millisecond re-runs.
_CAUSAL_CACHE_LIMIT = 256

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CausalEdge:
    """A single directed causal edge ``source → target``."""

    source: str
    target: str
    weight: float
    mechanism: CausalMechanism

    def key(self) -> tuple[str, str]:
        return (self.source, self.target)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "weight": round(self.weight, 3),
            "mechanism": self.mechanism,
        }

@dataclass(frozen=True)
class CausalGraph:
    """The synthetic causal graph derived from a :class:`FactsSnapshot`.

    Edges are stored as a tuple of :class:`CausalEdge` to keep the class
    hashable and deterministic.  Neighbour lookups are O(n) but the graph
    is small in practice (one edge per dependency / cause in the
    snapshot), which is acceptable for the F-141 MVP.
    """

    nodes: frozenset[str] = field(default_factory=frozenset)
    edges: tuple[CausalEdge, ...] = ()
    snapshot_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotHash": self.snapshot_hash,
            "nodes": sorted(self.nodes),
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def outgoing(self, node: str) -> tuple[CausalEdge, ...]:
        return tuple(edge for edge in self.edges if edge.source == node)

    def incoming(self, node: str) -> tuple[CausalEdge, ...]:
        return tuple(edge for edge in self.edges if edge.target == node)

    def edge_between(self, source: str, target: str) -> CausalEdge | None:
        for edge in self.edges:
            if edge.source == source and edge.target == target:
                return edge
        return None

@dataclass(frozen=True)
class CausalEffect:
    """Result of an ``intervene.do`` query.

    ``causal_effect`` is the raw intervention effect in the [0.0, 1.0]
    range.  ``weight`` is the *normalised* causal weight (rounded to
    three decimals for deterministic audit comparisons).
    """

    causal_effect: float
    is_significant: bool
    mechanism: CausalMechanism
    weight: float
    tag: CausalTag
    source: str
    target: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "causalEffect": round(self.causal_effect, 3),
            "isSignificant": self.is_significant,
            "mechanism": self.mechanism,
            "causalWeight": round(self.weight, 3),
            "tag": self.tag,
            "source": self.source,
            "target": self.target,
        }

@dataclass(frozen=True)
class Baseline:
    """Result of an ``observe.predict`` query."""

    value: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(self.confidence, 3),
        }

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CausalEngine:
    """In-process causal engine that implements the CAP verb surface.

    The engine is intentionally side-effect free: it never mutates the
    underlying snapshot, never issues network calls, and never imports
    third-party libraries.  All numeric outputs are deterministic (sorted
    iteration, fixed rounding precision).
    """

    def __init__(self, *, max_cache_entries: int = _CAUSAL_CACHE_LIMIT) -> None:
        self._cache: OrderedDict[tuple[str, tuple[str, str, str, str], str], CausalEffect] = (
            OrderedDict()
        )
        self._max_cache = max(1, int(max_cache_entries))
        self._lock = threading.Lock()

    # -- meta.capabilities ------------------------------------------------

    def meta_capabilities(self) -> dict[str, Any]:
        return {"verbs": list(CAP_VERBS)}

    # -- graph.neighbors --------------------------------------------------

    def graph_neighbors(
        self,
        graph: CausalGraph,
        node: str,
        scope: CausalScope,
    ) -> list[str]:
        if scope not in ("parents", "children", "ancestors", "descendants"):
            raise ValueError(f"Unsupported scope: {scope!r}")
        if node not in graph.nodes:
            return []
        if scope == "parents":
            return sorted({edge.source for edge in graph.incoming(node)})
        if scope == "children":
            return sorted({edge.target for edge in graph.outgoing(node)})
        if scope == "ancestors":
            return sorted(_transitive(graph, node, direction="up"))
        return sorted(_transitive(graph, node, direction="down"))

    # -- intervene.do -----------------------------------------------------

    def intervene_do(
        self,
        graph: CausalGraph,
        treatment_node: str,
        treatment_value: str,
        outcome_node: str,
    ) -> CausalEffect:
        """Estimate the standardised causal effect of ``treatment_node`` on
        ``outcome_node`` when forced to ``treatment_value``.

        For the synthetic MVP graph the effect is computed as:

        1. Locate the (direct or proof-driven) edge from treatment to
           outcome.  If none exists, fall back to the strongest
           ``structural`` path; if there is no path at all, return
           ``causal_effect=0.0``, ``mechanism="null"``.
        2. The raw effect is the edge's weight, optionally reduced by a
           length-based discount on indirect paths.
        3. ``causal_weight`` is the effect normalised by the maximum
           observed effect in the graph (closed range [0.0, 1.0]).

        The result is cached by ``(snapshot_hash, source, target,
        treatment_value)`` so repeated F-137 re-runs hit a single-digit
        millisecond cache.
        """
        if not isinstance(treatment_value, str):
            raise TypeError("treatment_value must be a string")
        cache_key = (
            graph.snapshot_hash,
            (treatment_node, outcome_node, treatment_value, "do"),
            "",
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        edge = graph.edge_between(treatment_node, outcome_node)
        if edge is not None:
            effect = _direct_effect(graph, edge, treatment_value)
            # When the treatment value is not in the "enabled" set the
            # edge's mechanism is irrelevant — we report ``null`` so the
            # caller can distinguish "no edge" from "edge exists but the
            # intervention value doesn't apply".
            mechanism: CausalMechanism = edge.mechanism if effect > 0.0 else "null"
        else:
            path = _shortest_path(graph, treatment_node, outcome_node)
            if path is None or len(path) < 2:
                effect, mechanism = 0.0, "null"
            else:
                effect = _path_effect(graph, path, treatment_value)
                mechanism = "indirect" if effect > 0.0 else "null"

        weight = _normalise(effect, graph)
        effect_result = CausalEffect(
            causal_effect=_clamp(effect),
            is_significant=weight >= SIGNIFICANT_THRESHOLD,
            mechanism=mechanism,
            weight=weight,
            tag=_tag_for(weight),
            source=treatment_node,
            target=outcome_node,
        )
        self._cache_put(cache_key, effect_result)
        return effect_result

    # -- observe.predict --------------------------------------------------

    def observe_predict(self, graph: CausalGraph, node: str) -> Baseline:
        """Return a baseline prediction for ``node``.

        The MVP baseline is derived from the *incoming* edge strengths:
        if the node has no incoming edges we return a neutral baseline;
        otherwise we return the strongest edge weight as the confidence
        proxy.  This deliberately keeps the verb cheap to evaluate.
        """
        incoming = graph.incoming(node)
        if not incoming:
            return Baseline(value="unknown", confidence=0.0)
        best = max(incoming, key=lambda edge: edge.weight)
        if best.weight >= SIGNIFICANT_THRESHOLD:
            return Baseline(value="likely_enabled", confidence=round(best.weight, 3))
        if best.weight >= MODERATE_THRESHOLD:
            return Baseline(value="possibly_enabled", confidence=round(best.weight, 3))
        return Baseline(value="uncertain", confidence=round(best.weight, 3))

    # -- cache ------------------------------------------------------------

    def _cache_get(
        self,
        key: tuple[str, tuple[str, str, str, str], str],
    ) -> CausalEffect | None:
        with self._lock:
            value = self._cache.get(key)
            if value is not None:
                # touch for LRU
                self._cache.move_to_end(key)
                return value
            return None

    def _cache_put(
        self,
        key: tuple[str, tuple[str, str, str, str], str],
        value: CausalEffect,
    ) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_cache:
                self._cache.popitem(last=False)

    def cache_info(self) -> dict[str, int]:
        with self._lock:
            return {"size": len(self._cache), "max": self._max_cache}

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_causal_graph(
    snapshot: "FactsSnapshot",
    *,
    tasks_view: dict[str, dict[str, Any]] | None = None,
) -> CausalGraph:
    """Seed a :class:`CausalGraph` from a :class:`FactsSnapshot`.

    Seeding order (per spec §10.6):

    1. ``metadata.lkb.causes`` declarations on the source task (manual
       labels — the most specific signal).
    2. ``metadata.lkb.acceptance_proof`` references that touch the
       target task (proof-driven edges).
    3. Layer-1 ``Requires`` / ``blockedBy`` edges as a weak default
       (weight=0.5, mechanism="structural").

    All input text is sanitised through :func:`_safe_weight` so F-139's
    rule that no natural-language text enters a weight computation is
    upheld.
    """
    if tasks_view is None:
        # Prefer the raw ``snapshot.tasks`` view because the
        # ``_normalize_task`` projection strips task-specific LKB
        # metadata (``causes``, custom fields) that we need for seeding.
        tasks_view = snapshot.tasks or snapshot.normalized_tasks
    nodes: set[str] = set()
    edges_by_key: dict[tuple[str, str], CausalEdge] = {}

    # Pass 1 — manual cause declarations.
    for task_id, task in sorted(tasks_view.items()):
        if not isinstance(task, dict):
            continue
        causes = _extract_causes(task)
        for target, raw_weight in causes:
            nodes.add(task_id)
            nodes.add(target)
            weight = _safe_weight(raw_weight, default=0.0)
            key = (task_id, target)
            existing = edges_by_key.get(key)
            if existing is None or weight > existing.weight:
                edges_by_key[key] = CausalEdge(
                    source=task_id,
                    target=target,
                    weight=weight,
                    mechanism="direct",
                )

    # Pass 2 — proof-driven edges.
    for task_id, task in sorted(tasks_view.items()):
        if not isinstance(task, dict):
            continue
        for target in _extract_proof_references(task):
            nodes.add(task_id)
            nodes.add(target)
            key = (task_id, target)
            existing = edges_by_key.get(key)
            if existing is None:
                edges_by_key[key] = CausalEdge(
                    source=task_id,
                    target=target,
                    weight=0.6,
                    mechanism="proof",
                )

    # Pass 3 — structural fallback (requires / blocked_by).
    for source, targets in sorted(snapshot.dependency_graph.items()):
        for target in sorted(targets):
            nodes.add(source)
            nodes.add(target)
            key = (source, target)
            existing = edges_by_key.get(key)
            if existing is None:
                edges_by_key[key] = CausalEdge(
                    source=source,
                    target=target,
                    weight=0.5,
                    mechanism="structural",
                )

    return CausalGraph(
        nodes=frozenset(nodes),
        edges=tuple(edges_by_key[key] for key in sorted(edges_by_key)),
        snapshot_hash=snapshot.hash,
    )

# ---------------------------------------------------------------------------
# Strict-mode helper
# ---------------------------------------------------------------------------

def is_strict_causal_enabled() -> bool:
    """Return True when the ``LKB_STRICT_CAUSAL`` env var is truthy.

    Strict mode is opt-in.  When enabled, the service turns a ``weak``
    causal outcome into a binding denial; when disabled the causal gate
    is purely advisory.
    """
    value = os.environ.get("LKB_STRICT_CAUSAL", "")
    return value.strip().lower() in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_causes(task: dict[str, Any]) -> list[tuple[str, float]]:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    lkb = metadata.get("lkb") if isinstance(metadata.get("lkb"), dict) else {}
    raw = lkb.get("causes") if isinstance(lkb.get("causes"), list) else []
    out: list[tuple[str, float]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        weight = entry.get("weight")
        if isinstance(target, str) and target and isinstance(weight, (int, float)):
            out.append((target, float(weight)))
    return out

def _extract_proof_references(task: dict[str, Any]) -> list[str]:
    """Return the list of tasks referenced by ``metadata.lkb.acceptance_proof``.

    The acceptance proof may be a string (task id), a list of strings, or a
    dict with a ``task_id`` / ``target`` field.  The function deliberately
    ignores any other shape so that natural-language text never reaches
    the causal weight computation.
    """
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    lkb = metadata.get("lkb") if isinstance(metadata.get("lkb"), dict) else {}
    proof = lkb.get("acceptance_proof")
    targets: list[str] = []
    if isinstance(proof, str) and proof:
        targets.append(proof)
    elif isinstance(proof, list):
        for entry in proof:
            if isinstance(entry, str) and entry:
                targets.append(entry)
            elif isinstance(entry, dict):
                value = entry.get("task_id") or entry.get("target")
                if isinstance(value, str) and value:
                    targets.append(value)
    elif isinstance(proof, dict):
        value = proof.get("task_id") or proof.get("target")
        if isinstance(value, str) and value:
            targets.append(value)
    return targets

def _safe_weight(value: Any, *, default: float) -> float:
    """Coerce ``value`` to a safe weight, ignoring any non-numeric text."""
    if isinstance(value, bool):  # bool is a subclass of int — guard explicitly
        return _clamp(float(value))
    if isinstance(value, (int, float)):
        return _clamp(float(value))
    return _clamp(default)

def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return float(value)

def _tag_for(weight: float) -> CausalTag:
    if weight >= SIGNIFICANT_THRESHOLD:
        return "significant"
    if weight >= MODERATE_THRESHOLD:
        return "moderate"
    return "weak"

def _normalise(effect: float, graph: CausalGraph) -> float:
    """Normalise ``effect`` to [0.0, 1.0] by the graph's max observable effect."""
    if not graph.edges:
        return 0.0
    max_effect = max(edge.weight for edge in graph.edges)
    if max_effect <= 0:
        return 0.0
    return round(_clamp(effect / max_effect), 3)

def _direct_effect(
    graph: CausalGraph,
    edge: CausalEdge,
    treatment_value: str,
) -> float:
    """Compute the raw effect of forcing ``treatment_value`` on a direct edge."""
    base = edge.weight
    if treatment_value not in {"completed", "1", "true", "on", "done"}:
        return 0.0
    return base

def _path_effect(
    graph: CausalGraph,
    path: tuple[str, ...],
    treatment_value: str,
) -> float:
    """Compute the raw effect along an indirect path of length >= 2."""
    if len(path) < 2:
        return 0.0
    if treatment_value not in {"completed", "1", "true", "on", "done"}:
        return 0.0
    product = 1.0
    for src, dst in zip(path, path[1:]):
        edge = graph.edge_between(src, dst)
        if edge is None:
            return 0.0
        product *= edge.weight
    # Discount the indirect effect by 0.85 per hop to avoid masking a
    # weak direct edge with a long chain of moderately-strong hops.
    discount = 0.85 ** max(0, len(path) - 2)
    return product * discount

def _shortest_path(
    graph: CausalGraph,
    source: str,
    target: str,
) -> tuple[str, ...] | None:
    if source == target:
        return (source,)
    if source not in graph.nodes or target not in graph.nodes:
        return None
    visited: set[str] = {source}
    queue: list[tuple[str, ...]] = [(source,)]
    while queue:
        path = queue.pop(0)
        head = path[-1]
        for edge in graph.outgoing(head):
            nxt = edge.target
            if nxt in visited:
                continue
            visited.add(nxt)
            new_path = path + (nxt,)
            if nxt == target:
                return new_path
            queue.append(new_path)
    return None

def _transitive(
    graph: CausalGraph,
    node: str,
    *,
    direction: Literal["up", "down"],
) -> set[str]:
    seen: set[str] = set()
    stack = [node]
    while stack:
        head = stack.pop()
        edges = graph.incoming(head) if direction == "up" else graph.outgoing(head)
        for edge in edges:
            nxt = edge.source if direction == "up" else edge.target
            if nxt in seen or nxt == node:
                continue
            seen.add(nxt)
            stack.append(nxt)
    return seen

# ---------------------------------------------------------------------------
# JSON serialisation helper (for the audit log wire format)
# ---------------------------------------------------------------------------

def to_wire_json(payload: dict[str, Any]) -> str:
    """Stable JSON serialisation for the audit-log wire format.

    The audit log records the exact JSON shape used by the HTTP service in
    spec §10.6 so the eventual move to a real CAP daemon is a transport
    swap only.  ``sort_keys`` + ``ensure_ascii=False`` keeps the output
    deterministic for diff-friendly audit logs.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)

__all__ = [
    "Baseline",
    "CAP_VERBS",
    "CausalEdge",
    "CausalEffect",
    "CausalEngine",
    "CausalGraph",
    "CausalMechanism",
    "CausalScope",
    "CausalTag",
    "MODERATE_THRESHOLD",
    "SIGNIFICANT_THRESHOLD",
    "build_causal_graph",
    "is_strict_causal_enabled",
    "to_wire_json",
]
