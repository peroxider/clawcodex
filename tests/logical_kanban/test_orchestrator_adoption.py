"""Tests for F-140 Orchestrator Adoption Through Todo Tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    acceptance_proof_required,
    latest_denial_for_task,
    read_audit_events_for_run,
    task_list_summary,
    task_ready_state,
    validate_task_transition,
)
from clawcodex_ext.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskGetTool, TaskUpdateTool


def _set_lkb(monkeypatch, enabled: bool) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> ToolContext:
    _set_lkb(monkeypatch, True)
    return ToolContext(workspace_root=tmp_path)


def _create_task(context: ToolContext, subject: str) -> str:
    return TaskCreateTool.call({"subject": subject, "description": subject}, context).output[
        "task"
    ]["id"]


def test_validate_task_transition_denies_blocked_start(context: ToolContext) -> None:
    blocker = _create_task(context, "Blocker")
    blocked = _create_task(context, "Blocked")
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, context)

    result = validate_task_transition(context, blocked, "in_progress")

    assert result["allowed"] is False
    assert result["decision"] == "denied"
    assert result["result"] == "fail"
    assert result["message"]
    assert result["repairSuggestions"]
    assert context.tasks[blocked]["status"] == "pending"


def test_validate_task_transition_allows_unblocked_start(context: ToolContext) -> None:
    task_id = _create_task(context, "Task")

    result = validate_task_transition(context, task_id, "in_progress")

    assert result["allowed"] is True
    assert result["decision"] == "committed"
    assert result["result"] == "pass"
    assert result["validationRunId"].startswith("V-")
    # The facade validates only; the caller must apply the change via TaskUpdateTool.
    assert context.tasks[task_id]["status"] == "pending"


def test_validate_task_transition_allows_after_blocker_completed(context: ToolContext) -> None:
    blocker = _create_task(context, "Blocker")
    blocked = _create_task(context, "Blocked")
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, context)
    denied = validate_task_transition(context, blocked, "in_progress")
    assert denied["allowed"] is False

    TaskUpdateTool.call({"taskId": blocker, "status": "completed"}, context)
    allowed = validate_task_transition(context, blocked, "in_progress")
    assert allowed["allowed"] is True
    assert allowed["decision"] == "committed"

    TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, context)
    assert context.tasks[blocked]["status"] == "in_progress"


def test_validate_task_transition_denies_completion_without_acceptance_proof(
    context: ToolContext,
) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    get_logical_kanban(context).strict_acceptance_enabled = True
    task_id = _create_task(context, "Task")
    TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, context)

    result = validate_task_transition(context, task_id, "completed")

    assert result["allowed"] is False
    assert result["decision"] == "denied"
    assert result["result"] == "fail"
    # The facade validates only; it does not mutate task status.
    assert context.tasks[task_id]["status"] == "in_progress"


def test_validate_task_transition_allows_completion_with_acceptance_proof(
    context: ToolContext,
) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    get_logical_kanban(context).strict_acceptance_enabled = True
    task_id = _create_task(context, "Task")
    TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, context)

    result = validate_task_transition(
        context,
        task_id,
        "completed",
    )
    assert result["allowed"] is False

    TaskUpdateTool.call(
        {
            "taskId": task_id,
            "status": "completed",
            "metadata": {"lkb": {"acceptance_proof": "tests passed"}},
        },
        context,
    )
    result = validate_task_transition(context, task_id, "completed")

    assert result["allowed"] is True
    assert result["decision"] == "committed"
    assert context.tasks[task_id]["status"] == "completed"


def test_validate_task_transition_disabled_allows_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, False)
    ctx = ToolContext(workspace_root=tmp_path)
    task_id = _create_task(ctx, "Task")

    result = validate_task_transition(ctx, task_id, "in_progress")

    assert result["allowed"] is True
    assert result["decision"] == "committed"
    assert result["message"] == "Logical Kanban is disabled; transition allowed by default."


def test_task_ready_state_reports_blocked_and_ready(context: ToolContext) -> None:
    blocker = _create_task(context, "Blocker")
    blocked = _create_task(context, "Blocked")
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, context)

    blocked_state = task_ready_state(context, blocked)
    assert blocked_state["status"] == "pending"
    assert blocked_state["derivedStatus"] == "blocked"
    assert blocked_state["blockedBy"] == [blocker]
    assert blocked_state["blockedReason"]
    assert blocked_state["nextActions"]

    ready_state = task_ready_state(context, blocker)
    assert ready_state["derivedStatus"] == "ready"
    assert ready_state["blockedBy"] == []


def test_task_ready_state_reports_missing_task(context: ToolContext) -> None:
    state = task_ready_state(context, "missing-task")

    assert state["derivedStatus"] == "needs_recheck"
    assert state["blockedReason"]


def test_task_list_summary_is_deterministic_and_includes_lkb(context: ToolContext) -> None:
    first_id = _create_task(context, "First")
    second_id = _create_task(context, "Second")
    TaskUpdateTool.call({"taskId": second_id, "addBlockedBy": [first_id]}, context)

    summary = task_list_summary(context)

    assert len(summary) == 2
    assert [row["id"] for row in summary] == sorted([first_id, second_id])
    blocked_row = [row for row in summary if row["id"] == second_id][0]
    assert blocked_row["blockedBy"] == [first_id]
    assert blocked_row["lkb"]["derivedStatus"] == "blocked"


def test_latest_denial_for_task_matches_task_get(context: ToolContext) -> None:
    blocker = _create_task(context, "Blocker")
    blocked = _create_task(context, "Blocked")
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, context)
    denied = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, context)

    from_orchestrator = latest_denial_for_task(context, blocked)
    from_task_get = TaskGetTool.call({"taskId": blocked}, context).output["task"]["lkb"][
        "latestDenialReason"
    ]

    assert from_orchestrator is not None
    assert from_orchestrator["validationRunId"] == denied.output["lkb"]["validationRunId"]
    assert from_orchestrator["validationRunId"] == from_task_get["validationRunId"]


def test_acceptance_proof_required_respects_runtime_flag(context: ToolContext) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    task_id = _create_task(context, "Task")
    assert acceptance_proof_required(context, task_id) is False

    get_logical_kanban(context).strict_acceptance_enabled = True
    assert acceptance_proof_required(context, task_id) is True


def test_acceptance_proof_required_respects_task_metadata(context: ToolContext) -> None:
    task_id = _create_task(context, "Task")
    context.tasks[task_id]["metadata"] = {"lkb": {"strict_acceptance": True}}

    assert acceptance_proof_required(context, task_id) is True


def test_read_audit_events_for_run_returns_commit_and_denial_events(
    context: ToolContext,
) -> None:
    blocker = _create_task(context, "Blocker")
    blocked = _create_task(context, "Blocked")
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, context)
    validate_task_transition(context, blocked, "in_progress")
    TaskUpdateTool.call({"taskId": blocker, "status": "completed"}, context)
    validate_task_transition(context, blocked, "in_progress")

    events = read_audit_events_for_run(context)
    event_types = [e["eventType"] for e in events]

    assert "lkb_denial" in event_types
    assert "lkb_commit" in event_types


def test_read_audit_events_for_run_filters_by_validation_run_id(
    context: ToolContext,
) -> None:
    task_a = _create_task(context, "Task A")
    task_b = _create_task(context, "Task B")
    result_a = validate_task_transition(context, task_a, "in_progress")
    result_b = validate_task_transition(context, task_b, "in_progress")
    run_id_a = result_a["validationRunId"]
    run_id_b = result_b["validationRunId"]

    assert run_id_a != run_id_b
    assert run_id_a.startswith("V-")

    events = read_audit_events_for_run(context, run_id=run_id_a)

    assert len(events) >= 1
    assert all(e.get("validationRunId") == run_id_a for e in events)
    assert not any(e.get("validationRunId") == run_id_b for e in events)


def test_read_audit_events_for_run_filters_by_task_id(context: ToolContext) -> None:
    task_a = _create_task(context, "Task A")
    task_b = _create_task(context, "Task B")
    validate_task_transition(context, task_a, "in_progress")
    validate_task_transition(context, task_b, "in_progress")

    events = read_audit_events_for_run(context, task_id=task_a)

    assert len(events) >= 1
    assert all(e.get("taskId") == task_a for e in events)


def test_orchestrator_prompt_includes_task_v2_guidance_when_enabled(
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = SimpleNamespace(
        identifier="TEST-1",
        title="Test issue",
        description="Test description",
        priority="medium",
        state="backlog",
        to_dict=lambda: {
            "identifier": "TEST-1",
            "title": "Test issue",
            "description": "Test description",
            "priority": "medium",
            "state": "backlog",
        },
    )
    rendered = PromptBuilder.render(issue)

    assert "Task tracking guidelines" in rendered
    assert "TaskCreate" in rendered
    assert "acceptance_proof" in rendered


def test_orchestrator_prompt_omits_task_v2_guidance_when_disabled(
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, False)
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = SimpleNamespace(
        identifier="TEST-1",
        title="Test issue",
        description="Test description",
        priority="medium",
        state="backlog",
        to_dict=lambda: {
            "identifier": "TEST-1",
            "title": "Test issue",
            "description": "Test description",
            "priority": "medium",
            "state": "backlog",
        },
    )
    rendered = PromptBuilder.render(issue)

    assert "Task tracking guidelines" not in rendered
    assert "TaskCreate" not in rendered


def test_orchestrator_facade_does_not_expose_solver_internals() -> None:
    """The facade module should not directly import solver internals."""
    import inspect

    import clawcodex_ext.logical_kanban.orchestrator as orchestrator_module

    source_lines = inspect.getsource(orchestrator_module).splitlines()
    forbidden = ("SolverAdapter", "SolverPipeline", "Layer1RuleEngine", "solver_adapter")
    import_lines = [line for line in source_lines if line.strip().startswith(("from ", "import "))]
    for line in import_lines:
        for name in forbidden:
            assert name not in line, f"orchestrator.py should not import {name}: {line}"
