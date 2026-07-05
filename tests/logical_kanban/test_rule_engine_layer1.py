from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot
from clawcodex_ext.logical_kanban.rule_engine import Layer1RuleEngine, evaluate_rules
from clawcodex_ext.tool_system.context import ToolContext


@pytest.fixture
def engine() -> Layer1RuleEngine:
    return Layer1RuleEngine()


@pytest.fixture
def empty_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


def _add_task(
    context: ToolContext,
    task_id: str,
    *,
    status: str = "pending",
    blocked_by: list[str] | None = None,
    blocks: list[str] | None = None,
    acceptance_proof: str | None = None,
) -> None:
    metadata: dict[str, Any] = {}
    if acceptance_proof is not None:
        metadata["lkb"] = {"acceptance_proof": acceptance_proof}
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
        "metadata": metadata,
    }


def test_r001_blocked_when_prerequisite_not_done(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"], blocks=[])
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "fail"
    assert result.violated_rule == "R-002"
    assert f"Blocked(B)" in result.derived_facts
    assert f"NotCanMoveTo(B, in_progress)" in result.derived_facts
    r001_traces = [t for t in result.proof_trace if t["rule"] == "R-001"]
    assert r001_traces
    assert f"Requires(A, B)" in r001_traces[0]["premises"]
    assert f"NotDone(A)" in r001_traces[0]["premises"]
    assert r001_traces[0]["conclusion"] == "Blocked(B)"


def test_r002_blocked_cannot_enter_in_progress(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "fail"
    assert result.violated_rule == "R-002"
    r002_traces = [t for t in result.proof_trace if t["rule"] == "R-002"]
    assert r002_traces
    assert r002_traces[0]["premises"] == ["Blocked(B)"]
    assert r002_traces[0]["conclusion"] == "NotCanMoveTo(B, in_progress)"


def test_r003_r004_ready_when_unblocked(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "B", status="pending")
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "pass"
    assert f"Ready(B)" in result.derived_facts
    assert f"CanMoveTo(B, in_progress)" in result.derived_facts
    assert any(t["rule"] == "R-003" for t in result.proof_trace)
    assert any(t["rule"] == "R-004" for t in result.proof_trace)


def test_r005_strict_acceptance_requires_proof(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "T", status="in_progress")
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(
        snapshot,
        target_task_id="T",
        target_status="completed",
        strict_acceptance=True,
    )

    assert result.result == "fail"
    assert result.violated_rule == "R-005"
    assert "completed" in result.message
    assert "acceptance proof" in result.message.lower()


def test_r005_accepts_completion_with_proof(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "T", status="in_progress", acceptance_proof="tests passed")
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(
        snapshot,
        target_task_id="T",
        target_status="completed",
        strict_acceptance=True,
    )

    assert result.result == "pass"
    assert f"HasAcceptanceProof(T)" in result.derived_facts
    assert f"CanMoveTo(T, completed)" in result.derived_facts


def test_r006_cycle_invalidates_readiness(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="pending", blocked_by=["B"], blocks=["B"])
    _add_task(empty_context, "B", status="pending", blocked_by=["A"], blocks=["A"])
    snapshot = build_facts_snapshot(empty_context)

    assert snapshot.cycle_task_ids == {"A", "B"}

    result = engine.evaluate(snapshot, target_task_id="A", target_status="in_progress")

    assert result.result == "fail"
    assert result.violated_rule == "R-006"
    assert set(result.cycle_tasks) == {"A", "B"}
    assert f"NotReady(A)" in result.derived_facts
    assert f"NotCanMoveTo(A, in_progress)" in result.derived_facts


def test_completed_blocker_no_longer_blocks(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "pass"
    assert f"Ready(B)" in result.derived_facts
    assert f"CanMoveTo(B, in_progress)" in result.derived_facts
    assert "Blocked(B)" not in result.derived_facts


def test_evaluate_without_query_returns_all_derived_facts(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot)

    assert result.result == "pass"
    assert f"Ready(A)" in result.derived_facts
    assert f"CanMoveTo(A, in_progress)" in result.derived_facts
    assert f"Blocked(B)" in result.derived_facts
    assert f"NotCanMoveTo(B, in_progress)" in result.derived_facts


def test_determinism(engine: Layer1RuleEngine, empty_context: ToolContext) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    _add_task(empty_context, "C", status="pending")
    snapshot = build_facts_snapshot(empty_context)

    first = engine.evaluate(snapshot)
    second = engine.evaluate(snapshot)

    assert first.derived_facts == second.derived_facts
    assert first.proof_trace == second.proof_trace


def test_proof_trace_format_matches_spec(
    engine: Layer1RuleEngine, empty_context: ToolContext
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])
    snapshot = build_facts_snapshot(empty_context)

    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "fail"
    for trace in result.proof_trace:
        assert "rule" in trace
        assert "premises" in trace
        assert "conclusion" in trace


def test_evaluate_rules_convenience_entry_point(
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "B", status="pending")
    snapshot = build_facts_snapshot(empty_context)

    result = evaluate_rules(snapshot, target_task_id="B", target_status="in_progress")

    assert result.result == "pass"
    assert f"Ready(B)" in result.derived_facts


def test_from_context_builds_snapshot(tmp_path: Path) -> None:
    engine = Layer1RuleEngine()
    ctx = ToolContext(workspace_root=tmp_path)
    _add_task(ctx, "B", status="pending")

    snapshot = engine.from_context(ctx)

    assert snapshot.hash.startswith("sha256:")
    result = engine.evaluate(snapshot, target_task_id="B", target_status="in_progress")
    assert result.result == "pass"


def test_performance_1000_tasks(empty_context: ToolContext) -> None:
    engine = Layer1RuleEngine()
    n = 1000
    for i in range(n):
        prev = f"t{i - 1}" if i > 0 else None
        blocked_by = [prev] if prev else []
        blocks = [f"t{i + 1}"] if i < n - 1 else []
        _add_task(empty_context, f"t{i}", status="pending", blocked_by=blocked_by, blocks=blocks)

    snapshot = build_facts_snapshot(empty_context)

    start = time.perf_counter()
    result = engine.evaluate(snapshot, target_task_id="t999", target_status="in_progress")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result.result == "fail"
    assert elapsed_ms < 200, f"Rule engine took {elapsed_ms:.1f}ms for 1000 tasks"
