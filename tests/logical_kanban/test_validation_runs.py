"""Tests for F-133 Validation Runs and Proof Trace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    LogicalKanbanService,
    ProposedChange,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot
from clawcodex_ext.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskUpdateTool


def _set_lkb(monkeypatch, enabled: bool) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


@pytest.fixture
def service() -> LogicalKanbanService:
    return LogicalKanbanService()


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
) -> None:
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "description": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
        "metadata": {},
    }


def test_validation_run_has_canonical_f133_fields(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    change = ProposedChange(
        kind="create_task",
        payload={"taskId": "T1"},
        actor="test-agent",
    )
    proposal, validation, _commit = service.run(change, empty_context)

    assert validation.validation_run_id.startswith("V-")
    assert validation.proposal_id.startswith("P-")
    assert validation.proposal_id == proposal.proposal_id
    assert validation.task_id == "T1"
    assert validation.input_facts_hash.startswith("sha256:")
    assert validation.ruleset_hash.startswith("sha256:")
    assert validation.engine == "layer1-python"
    assert validation.engine_version == service.solver_version
    assert validation.result == "pass"
    assert validation.duration_ms >= 0
    assert validation.created_at.endswith("+00:00")
    assert validation.requested_by == "test-agent"


def test_validation_run_hash_is_deterministic_for_identical_snapshots(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", status="completed")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])

    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )

    first = service.validate(service.propose(change, empty_context), empty_context)
    second = service.validate(service.propose(change, empty_context), empty_context)

    assert first.input_facts_hash == second.input_facts_hash
    assert first.ruleset_hash == second.ruleset_hash
    assert first.result == second.result == "pass"


def test_failed_validation_includes_human_reason_and_repair_suggestions(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])

    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)

    assert validation.result == "fail"
    assert validation.issues
    issue = validation.issues[0]
    assert "cannot enter in_progress" in issue.message
    assert issue.repair_suggestions
    assert any(s.action == "complete_prerequisite" for s in issue.repair_suggestions)
    assert validation.counterexample is not None
    assert validation.counterexample.get("activeBlockers") == ["A"]


def test_proof_trace_is_compact_and_structured(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    _add_task(empty_context, "A", status="pending")
    _add_task(empty_context, "B", status="pending", blocked_by=["A"])

    change = ProposedChange(
        kind="transition_status",
        payload={"taskId": "B", "status": "in_progress"},
    )
    _proposal, validation, _commit = service.run(change, empty_context)

    assert validation.proof_trace
    for step in validation.proof_trace:
        assert "rule" in step
        assert "premises" in step
        assert "conclusion" in step


def test_task_update_output_exposes_validation_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"]["id"]

    result = TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

    assert result.is_error is False
    assert result.output["success"] is True
    lkb = result.output["lkb"]
    assert lkb["validationRunId"].startswith("V-")
    assert lkb["proposalId"].startswith("P-")
    assert lkb["taskId"] == task_id
    assert lkb["result"] == "pass"
    assert lkb["engine"] == "layer1-python"
    assert lkb["inputFactsHash"].startswith("sha256:")
    assert lkb["rulesetHash"].startswith("sha256:")
    assert "proofTrace" in lkb
    assert "validation" in lkb


def test_denied_task_update_includes_repair_suggestions_and_counterexample(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output["task"][
        "id"
    ]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output["task"][
        "id"
    ]
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

    result = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)

    assert result.is_error is True
    assert result.output["status"] == "denied"
    lkb = result.output["lkb"]
    assert lkb["decision"] == "denied"
    assert lkb["result"] == "fail"
    assert lkb["counterexample"]
    assert lkb["counterexample"].get("activeBlockers") == [blocker]
    assert lkb["repairSuggestions"]
    assert any(s["action"] == "complete_prerequisite" for s in lkb["repairSuggestions"])
    assert "humanMessage" in lkb


def test_validation_run_is_immutable(
    service: LogicalKanbanService,
    empty_context: ToolContext,
) -> None:
    change = ProposedChange(kind="create_task", payload={"taskId": "T1"})
    _proposal, validation, _commit = service.run(change, empty_context)

    with pytest.raises(AttributeError):
        validation.result = "fail"  # type: ignore[misc]
