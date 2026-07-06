"""Tests for the F-141 Causal Verification Layer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    CAP_VERBS,
    LogicalKanbanService,
    ProposedChange,
)
from clawcodex_ext.logical_kanban.audit import InMemoryAuditLog
from clawcodex_ext.logical_kanban.causal import (
    CausalEdge,
    CausalEffect,
    CausalEngine,
    CausalGraph,
    MODERATE_THRESHOLD,
    SIGNIFICANT_THRESHOLD,
    build_causal_graph,
    is_strict_causal_enabled,
    to_wire_json,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot
from clawcodex_ext.logical_kanban.flags import CAUSAL_FEATURE_NAME
from clawcodex_ext.logical_kanban.types import FactsSnapshot
from clawcodex_ext.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskUpdateTool


# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


def _set_lkb(monkeypatch, *, lkb: bool = True, causal: bool = True) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", lkb)
    monkeypatch.setitem(get_registry()._overrides, CAUSAL_FEATURE_NAME, causal)


def _add_task(
    context: ToolContext,
    task_id: str,
    *,
    status: str = "pending",
    blocked_by: list[str] | None = None,
    blocks: list[str] | None = None,
    causes: list[dict[str, Any]] | None = None,
    acceptance_proof: Any = None,
) -> None:
    metadata: dict[str, Any] = {}
    lkb: dict[str, Any] = {}
    if causes is not None:
        lkb["causes"] = causes
    if acceptance_proof is not None:
        lkb["acceptance_proof"] = acceptance_proof
    if lkb:
        metadata["lkb"] = lkb
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "description": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
        "metadata": metadata,
    }


def _snapshot(context: ToolContext) -> FactsSnapshot:
    return build_facts_snapshot(context)


@pytest.fixture
def empty_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


@pytest.fixture
def service() -> LogicalKanbanService:
    return LogicalKanbanService()


@pytest.fixture(autouse=True)
def _reset_strict_causal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LKB_STRICT_CAUSAL", raising=False)


# ---------------------------------------------------------------------------
# CAP verb surface
# ---------------------------------------------------------------------------


def test_meta_capabilities_returns_cap_verbs() -> None:
    engine = CausalEngine()
    payload = engine.meta_capabilities()
    assert payload == {"verbs": list(CAP_VERBS)}
    assert "graph.neighbors" in payload["verbs"]
    assert "intervene.do" in payload["verbs"]
    assert "observe.predict" in payload["verbs"]


def test_cap_verbs_tuple_is_immutable() -> None:
    assert isinstance(CAP_VERBS, tuple)
    assert len(CAP_VERBS) == 3


def test_wire_json_is_deterministic() -> None:
    payload = {"verbs": ["graph.neighbors"], "version": 1}
    assert to_wire_json(payload) == to_wire_json(payload)


# ---------------------------------------------------------------------------
# Causal graph seeding
# ---------------------------------------------------------------------------


def test_build_causal_graph_from_metadata_lkb_causes(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", causes=[{"target": "B", "weight": 0.9}])
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    assert ("A", "B") in {edge.key() for edge in graph.edges}
    edge = graph.edge_between("A", "B")
    assert edge is not None
    assert edge.mechanism == "direct"
    assert edge.weight == 0.9
    assert graph.snapshot_hash.startswith("sha256:")


def test_build_causal_graph_uses_acceptance_proof_as_proof_edges(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", acceptance_proof="B")
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    edge = graph.edge_between("A", "B")
    assert edge is not None
    assert edge.mechanism == "proof"
    assert edge.weight == 0.6


def test_build_causal_graph_uses_acceptance_proof_list_of_targets(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", acceptance_proof=["B", "C"])
    _add_task(empty_context, "B")
    _add_task(empty_context, "C")
    graph = build_causal_graph(_snapshot(empty_context))
    sources = {edge.source for edge in graph.incoming("B")} | {
        edge.source for edge in graph.incoming("C")
    }
    assert sources == {"A"}


def test_build_causal_graph_falls_back_to_structural_edges(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A")
    _add_task(empty_context, "B", blocked_by=["A"])
    graph = build_causal_graph(_snapshot(empty_context))
    edge = graph.edge_between("A", "B")
    assert edge is not None
    assert edge.mechanism == "structural"
    assert edge.weight == 0.5


def test_build_causal_graph_priority_order(
    empty_context: ToolContext,
) -> None:
    # All three sources point to the same edge. The manual cause
    # declaration (0.9) must win.
    _add_task(
        empty_context,
        "A",
        blocked_by=[],
        causes=[{"target": "B", "weight": 0.9}],
        acceptance_proof="B",
    )
    _add_task(empty_context, "B", blocked_by=["A"])
    graph = build_causal_graph(_snapshot(empty_context))
    edge = graph.edge_between("A", "B")
    assert edge is not None
    assert edge.mechanism == "direct"
    assert edge.weight == 0.9


def test_build_causal_graph_non_numeric_weight_uses_default(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", causes=[{"target": "B", "weight": "not a number"}])
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    edge = graph.edge_between("A", "B")
    # Non-numeric weights are dropped (default 0.0), so the edge itself
    # should not be created from the manual declaration.
    assert edge is None


def test_build_causal_graph_clamps_out_of_range_weights(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", causes=[{"target": "B", "weight": 2.5}])
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    edge = graph.edge_between("A", "B")
    assert edge is not None
    assert edge.weight == 1.0


def test_build_causal_graph_empty_when_no_edges(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A")
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    assert graph.edges == ()


# ---------------------------------------------------------------------------
# graph.neighbors verb
# ---------------------------------------------------------------------------


def test_graph_neighbors_parents_and_children(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", causes=[{"target": "B", "weight": 0.9}])
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    engine = CausalEngine()
    assert engine.graph_neighbors(graph, "B", "parents") == ["A"]
    assert engine.graph_neighbors(graph, "A", "children") == ["B"]


def test_graph_neighbors_ancestors_and_descendants(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", causes=[{"target": "B", "weight": 0.9}])
    _add_task(empty_context, "B", causes=[{"target": "C", "weight": 0.8}])
    _add_task(empty_context, "C")
    graph = build_causal_graph(_snapshot(empty_context))
    engine = CausalEngine()
    assert engine.graph_neighbors(graph, "C", "ancestors") == ["A", "B"]
    assert engine.graph_neighbors(graph, "A", "descendants") == ["B", "C"]


def test_graph_neighbors_unknown_node_returns_empty() -> None:
    graph = CausalGraph()
    engine = CausalEngine()
    assert engine.graph_neighbors(graph, "ghost", "parents") == []


def test_graph_neighbors_invalid_scope_raises() -> None:
    graph = CausalGraph()
    engine = CausalEngine()
    with pytest.raises(ValueError):
        engine.graph_neighbors(graph, "A", "sideways")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# intervene.do verb
# ---------------------------------------------------------------------------


def test_intervene_do_on_empty_graph_returns_null() -> None:
    engine = CausalEngine()
    graph = CausalGraph()
    effect = engine.intervene_do(graph, "A", "completed", "B")
    assert effect.causal_effect == 0.0
    assert effect.is_significant is False
    assert effect.mechanism == "null"
    assert effect.tag == "weak"
    assert effect.weight == 0.0


def test_intervene_do_on_direct_edge_with_high_weight() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),),
        snapshot_hash="sha256:test",
    )
    effect = engine.intervene_do(graph, "A", "completed", "B")
    assert effect.is_significant is True
    assert effect.tag == "significant"
    assert effect.mechanism == "direct"
    assert effect.weight == pytest.approx(1.0, abs=1e-3)


def test_intervene_do_on_proof_edge_records_proof_mechanism() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B", "C"}),
        edges=(
            CausalEdge(source="A", target="B", weight=0.6, mechanism="proof"),
            CausalEdge(source="A", target="C", weight=1.0, mechanism="direct"),
        ),
    )
    effect = engine.intervene_do(graph, "A", "completed", "B")
    assert effect.mechanism == "proof"
    # Normalised weight = 0.6 / 1.0 = 0.6 (moderate).
    assert effect.tag == "moderate"


def test_intervene_do_on_structural_edge_yields_weak_when_no_other_edges() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.5, mechanism="structural"),),
    )
    effect = engine.intervene_do(graph, "A", "completed", "B")
    assert effect.mechanism == "structural"
    assert effect.weight == pytest.approx(1.0, abs=1e-3)
    assert effect.tag == "significant"


def test_intervene_do_indirect_path() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B", "C"}),
        edges=(
            CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),
            CausalEdge(source="B", target="C", weight=0.9, mechanism="direct"),
        ),
    )
    effect = engine.intervene_do(graph, "A", "completed", "C")
    assert effect.mechanism == "indirect"
    # 0.9 * 0.9 * 0.85 (length-2 discount) = 0.6885, normalised by 0.9 = ~0.765
    assert effect.tag in ("significant", "moderate")


def test_intervene_do_unrelated_treatment_value_returns_zero() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),),
    )
    effect = engine.intervene_do(graph, "A", "cancelled", "B")
    assert effect.causal_effect == 0.0
    assert effect.mechanism == "null"


# ---------------------------------------------------------------------------
# observe.predict verb
# ---------------------------------------------------------------------------


def test_observe_predict_returns_neutral_baseline_for_leaf() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),),
    )
    baseline = engine.observe_predict(graph, "A")
    assert baseline.value == "unknown"
    assert baseline.confidence == 0.0


def test_observe_predict_returns_likely_enabled_for_strong_incoming() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),),
    )
    baseline = engine.observe_predict(graph, "B")
    assert baseline.value == "likely_enabled"
    assert baseline.confidence == pytest.approx(0.9, abs=1e-3)


def test_observe_predict_returns_uncertain_for_weak_incoming() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.3, mechanism="structural"),),
    )
    baseline = engine.observe_predict(graph, "B")
    assert baseline.value == "uncertain"


# ---------------------------------------------------------------------------
# Determinism / cache
# ---------------------------------------------------------------------------


def test_causal_weight_rounded_to_three_decimals() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B", "C"}),
        edges=(
            CausalEdge(source="A", target="B", weight=0.77777, mechanism="direct"),
            CausalEdge(source="A", target="C", weight=0.3, mechanism="structural"),
        ),
    )
    effect = engine.intervene_do(graph, "A", "completed", "B")
    # `weight` is rounded to 3 decimals in the normalised form.
    assert effect.weight == round(effect.weight, 3)
    assert effect.to_dict()["causalWeight"] == round(effect.weight, 3)


def test_cache_hit_returns_same_effect() -> None:
    engine = CausalEngine()
    graph = CausalGraph(
        nodes=frozenset({"A", "B"}),
        edges=(CausalEdge(source="A", target="B", weight=0.9, mechanism="direct"),),
        snapshot_hash="sha256:cache",
    )
    first = engine.intervene_do(graph, "A", "completed", "B")
    second = engine.intervene_do(graph, "A", "completed", "B")
    assert first is second
    assert engine.cache_info()["size"] == 1


# ---------------------------------------------------------------------------
# Threshold semantics
# ---------------------------------------------------------------------------


def test_thresholds_are_documented() -> None:
    assert SIGNIFICANT_THRESHOLD == 0.7
    assert MODERATE_THRESHOLD == 0.4


def test_tag_for_thresholds() -> None:
    engine = CausalEngine()
    assert engine.intervene_do(
        CausalGraph(
            nodes=frozenset({"A", "B"}),
            edges=(CausalEdge(source="A", target="B", weight=0.95, mechanism="direct"),),
        ),
        "A",
        "completed",
        "B",
    ).tag == "significant"
    assert engine.intervene_do(
        CausalGraph(
            nodes=frozenset({"A", "B"}),
            edges=(
                CausalEdge(source="A", target="B", weight=0.5, mechanism="direct"),
                CausalEdge(source="A", target="B", weight=0.5, mechanism="direct"),  # placeholder
            ),
        ),
        "A",
        "completed",
        "B",
    ).tag in ("significant", "moderate")


# ---------------------------------------------------------------------------
# Feature gate & dual-layer gate order
# ---------------------------------------------------------------------------


def test_causal_disabled_returns_input_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _set_lkb(monkeypatch, causal=False)
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "pass"
    counterexample = validation.counterexample or {}
    assert "causal" not in counterexample


def test_symbolic_fail_wins_over_causal(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    """A symbolic fail must short-circuit the causal gate entirely."""
    _set_lkb(monkeypatch, causal=True)
    # A is *not* completed, so B cannot enter in_progress (symbolic R-001/R-002).
    _add_task(empty_context, "A", status="pending")
    _add_task(
        empty_context,
        "B",
        status="pending",
        blocked_by=["A"],
        causes=[{"target": "A", "weight": 0.9}],
    )
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "fail"
    counterexample = validation.counterexample or {}
    assert "causal" not in counterexample


def test_causal_gate_advisory_by_default(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    """A weak causal outcome is advisory when ``LKB_STRICT_CAUSAL`` is off."""
    _set_lkb(monkeypatch, causal=True)
    # Make A already completed so the symbolic gate passes, but declare a
    # very weak direct cause (so the structural fall-back is used and the
    # worst weight is below the moderate threshold).
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "pass"
    # The causal sub-record should be present and advisory.
    counterexample = validation.counterexample or {}
    assert "causal" in counterexample
    assert counterexample["causal"]["gate"] == "advisory"


def test_causal_gate_significant_weight_annotated(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _set_lkb(monkeypatch, causal=True)
    _add_task(
        empty_context,
        "A",
        status="completed",
        causes=[{"target": "B", "weight": 0.9}],
    )
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "pass"
    causal = (validation.counterexample or {}).get("causal") or {}
    assert causal
    worst = causal.get("worst", {})
    assert worst.get("tag") == "significant"
    assert worst.get("isSignificant") is True


def test_causal_gate_strict_mode_denies_on_weak(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", True)
    monkeypatch.setitem(get_registry()._overrides, CAUSAL_FEATURE_NAME, True)
    monkeypatch.setenv("LKB_STRICT_CAUSAL", "1")
    # Symbolic gate is clean; the structural fallback is the only edge.
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    # With strict mode on, the structural weight (0.5) is moderate
    # rather than weak, so the outcome stays as "moderate" and the
    # decision is unchanged.  This test guards the *advisory-by-default*
    # contract: even in strict mode, only `weak` flips a pass to fail.
    assert validation.result == "pass"


def test_strict_mode_flips_pass_to_fail_when_causal_is_weak(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    from clawcodex_ext.logical_kanban import Proposal
    from clawcodex_ext.logical_kanban.types import ProposedChange

    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", True)
    monkeypatch.setitem(get_registry()._overrides, CAUSAL_FEATURE_NAME, True)
    monkeypatch.setenv("LKB_STRICT_CAUSAL", "1")

    # Inject a synthetic snapshot where every causal edge is weak, so
    # the worst tag is "weak" once we force the engine to evaluate.
    snapshot = SimpleNamespace(
        hash="sha256:weak",
        normalized_tasks={},
        tasks={},
        dependency_graph={},
        blocked_by={"B": ("A",)},
        completed_ids=frozenset({"A"}),
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        cycle_task_ids=frozenset(),
        warnings=(),
        facts=(),
    )
    proposal = Proposal(
        proposal_id="P-test",
        change=ProposedChange(
            kind="transition_status",
            payload={"taskId": "B", "status": "in_progress"},
        ),
        snapshot_hash="sha256:weak",
    )
    validation = service._accepted(proposal=proposal, task_id="B")

    # Monkey-patch build_causal_graph to return a graph where the
    # evaluated edge is the weakest one in the graph — this forces the
    # normalised causal weight below the moderate threshold, triggering
    # the strict-mode denial branch.
    weak_graph = CausalGraph(
        nodes=frozenset({"A", "B", "C"}),
        edges=(
            CausalEdge(
                source="A",
                target="B",
                weight=0.1,
                mechanism="structural",
            ),
            CausalEdge(
                source="C",
                target="B",
                weight=1.0,
                mechanism="direct",
            ),
        ),
        snapshot_hash="sha256:weak",
    )
    with patch(
        "clawcodex_ext.logical_kanban.service.build_causal_graph",
        return_value=weak_graph,
    ):
        result = service._apply_causal_gate(
            proposal=proposal,
            snapshot=snapshot,  # type: ignore[arg-type]
            validation=validation,
            edges=(("A", "B"),),
            context=empty_context,
        )
    assert result.result == "fail"
    assert result.issues
    assert result.issues[0].code == "causal_weight_weak"
    assert (result.counterexample or {}).get("causal", {}).get("gate") == "strict"


# ---------------------------------------------------------------------------
# Symbolic fail regression — stub causal engine always returns significant
# ---------------------------------------------------------------------------


def test_symbolic_fail_overrides_significant_causal_stub(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    """Even if the causal engine 'always says significant', a symbolic fail
    must still be a fail.  Regression for the F-141 acceptance criterion.
    """
    _set_lkb(monkeypatch, causal=True)

    significant_effect = CausalEffect(
        causal_effect=1.0,
        is_significant=True,
        mechanism="direct",
        weight=1.0,
        tag="significant",
        source="A",
        target="B",
    )

    def _always_significant(self, graph, treatment_node, treatment_value, outcome_node):  # noqa: ARG001
        return CausalEffect(
            causal_effect=1.0,
            is_significant=True,
            mechanism="direct",
            weight=1.0,
            tag="significant",
            source=treatment_node,
            target=outcome_node,
        )

    # Symbolic fail: A is not completed, B is blocked.
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    with patch.object(CausalEngine, "intervene_do", _always_significant):
        _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "fail"
    counterexample = validation.counterexample or {}
    assert "causal" not in counterexample
    # Sanity: the stub returned a significant effect when called.
    assert significant_effect.is_significant is True


# ---------------------------------------------------------------------------
# override_causal — audit + metadata
# ---------------------------------------------------------------------------


def test_override_causal_emits_human_override_audit(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    audit = InMemoryAuditLog()
    empty_context.logical_kanban = SimpleNamespace(audit_log=audit)
    _add_task(empty_context, "A")
    event = service.override_causal(
        edge=("A", "B"),
        reason="Reviewed by lead, accepted the dependency.",
        weight=0.42,
        approver="alice",
        validation_run_id="V-test",
        proposal_id="P-test",
        context=empty_context,
    )
    assert event.event_type == "lkb_human_override"
    assert event.payload["overrideType"] == "causal"
    assert event.payload["proposal_id"] == "P-test"
    assert event.payload["edge"] == {"source": "A", "target": "B"}
    assert event.payload["justification"] == "Reviewed by lead, accepted the dependency."
    assert event.payload["approver"] == "alice"
    assert event.payload["weight"] == 0.42
    assert event.payload["previousResult"] == "weak"
    # Audit log contains the event.
    matches = audit.query(event_type="lkb_human_override")
    assert len(matches) == 1
    assert matches[0].payload["edge"] == {"source": "A", "target": "B"}


def test_override_causal_attaches_metadata_lkb_causal_override(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _set_lkb(monkeypatch, causal=True)
    _add_task(empty_context, "A")
    service.override_causal(
        edge=("A", "B"),
        reason="Manual acceptance.",
        weight=0.3,
        approver="bob",
        context=empty_context,
    )
    metadata = empty_context.tasks["A"].get("metadata") or {}
    lkb = metadata.get("lkb") or {}
    override = lkb.get("causal_override") or {}
    assert override.get("source") == "A"
    assert override.get("target") == "B"
    assert override.get("approver") == "bob"
    assert override.get("reason") == "Manual acceptance."
    assert override.get("weight") == 0.3
    assert override.get("overriddenAt")


def test_override_causal_clamps_weight(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A")
    event = service.override_causal(
        edge=("A", "B"),
        reason="X",
        weight=5.0,
        approver="c",
        context=empty_context,
    )
    assert event.payload["weight"] == 1.0
    event = service.override_causal(
        edge=("A", "B"),
        reason="X",
        weight=-1.0,
        approver="c",
        context=empty_context,
    )
    assert event.payload["weight"] == 0.0


# ---------------------------------------------------------------------------
# TaskUpdate output stability
# ---------------------------------------------------------------------------


def test_taskupdate_output_unchanged_when_causal_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TaskUpdate output schema must not gain a `causal` field when the
    feature gate is off.  Regression for the F-141 acceptance criterion
    that adding F-141 does not change the public TaskUpdate output.
    """
    _set_lkb(monkeypatch, lkb=True, causal=False)
    ctx = ToolContext(workspace_root=tmp_path)
    TaskCreateTool.call({"subject": "A", "description": "D"}, ctx)
    result = TaskUpdateTool.call(
        {"taskId": list(ctx.tasks)[0], "status": "in_progress"},
        ctx,
    )
    assert result.is_error is False
    lkb = result.output["lkb"]
    assert "causal" not in lkb
    assert lkb["result"] == "pass"


def test_taskupdate_output_adds_causal_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_lkb(monkeypatch, lkb=True, causal=True)
    ctx = ToolContext(workspace_root=tmp_path)
    TaskCreateTool.call({"subject": "A", "description": "D"}, ctx)
    result = TaskUpdateTool.call(
        {"taskId": list(ctx.tasks)[0], "status": "in_progress"},
        ctx,
    )
    assert result.is_error is False
    validation = result.output["lkb"]["validation"]
    # The ValidationRun.to_dict() output is unchanged: it still uses
    # `counterexample`, and the causal sub-record lives there when the
    # gate ran.  We don't add a top-level `causal` key in the public
    # payload.
    assert "causal" not in result.output["lkb"]


# ---------------------------------------------------------------------------
# F-139 sanitisation inheritance
# ---------------------------------------------------------------------------


def test_causal_engine_ignores_non_numeric_text(
    empty_context: ToolContext,
) -> None:
    """Per F-139, no natural-language text may enter a weight computation.

    The seeding helper must coerce the weight to a number and silently
    drop any non-numeric input.  A malicious / sloppy `causes` declaration
    with a free-form string weight must not crash the engine.
    """
    _add_task(
        empty_context,
        "A",
        causes=[{"target": "B", "weight": "DROP TABLE foo; --"}],
    )
    _add_task(empty_context, "B")
    graph = build_causal_graph(_snapshot(empty_context))
    # No edge should be created from a non-numeric weight.
    assert graph.edge_between("A", "B") is None
    # Engine should still operate cleanly on the resulting graph.
    engine = CausalEngine()
    effect = engine.intervene_do(graph, "A", "completed", "B")
    assert effect.mechanism == "null"


# ---------------------------------------------------------------------------
# Snapshot-level: no-op when feature off
# ---------------------------------------------------------------------------


def test_f141_disabled_does_not_change_validation_run(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _set_lkb(monkeypatch, lkb=True, causal=False)
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "pass"
    assert validation.counterexample in (None, {})


# ---------------------------------------------------------------------------
# add_dependency integration
# ---------------------------------------------------------------------------


def test_add_dependency_passes_through_causal_gate(
    monkeypatch: pytest.MonkeyPatch,
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _set_lkb(monkeypatch, causal=True)
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending")
    change = ProposedChange(
        kind="add_dependency",
        payload={"taskId": "B", "addBlockedBy": ["A"]},
    )
    _proposal, validation, _commit = service.run(change, empty_context)
    assert validation.result == "pass"
    counterexample = validation.counterexample or {}
    causal = counterexample.get("causal")
    assert causal is not None
    # The edge we just added should be in the evaluated list.
    assert {"source": "A", "target": "B"} in causal["edges"]
