"""Tests for F-136 Explainability and Repair Suggestions UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    LogicalKanbanService,
    ProposedChange,
    RepairSuggestion,
    explain_validation_run,
)
from clawcodex_ext.logical_kanban.context_adapter import task_lkb_view
from clawcodex_ext.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskGetTool, TaskUpdateTool


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
    acceptance_proof: str | None = None,
) -> None:
    metadata: dict[str, Any] = {}
    if acceptance_proof is not None:
        metadata["lkb"] = {"acceptance_proof": acceptance_proof}
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "description": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
        "metadata": metadata,
    }


class TestBlockedTaskExplanation:
    def test_blocked_task_explains_which_prerequisite_blocks_it(
        self,
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
        issue = validation.issues[0]
        assert issue.code == "blocked_task_cannot_enter_in_progress"
        assert "A" in issue.message
        assert issue.blockers == ("A",)
        assert any(
            s.action == "complete_prerequisite" and s.target == "A"
            for s in issue.repair_suggestions
        )
        assert any(s.action == "remove_dependency" for s in issue.repair_suggestions)
        assert validation.counterexample is not None
        assert validation.counterexample.get("activeBlockers") == ["A"]

    def test_blocked_task_includes_proof_trace(
        self,
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

        explanation = explain_validation_run(validation)
        assert explanation["result"] == "fail"
        assert "A" in explanation["summary"]
        assert explanation["proofTraceSummary"]
        rules = explanation["rulesUsed"]
        assert "R-001" in rules
        assert "R-002" in rules
        assert any(s["action"] == "complete_prerequisite" for s in explanation["repairSuggestions"])


class TestCycleExplanation:
    def test_cycle_denial_lists_every_task_in_the_cycle(
        self,
        service: LogicalKanbanService,
        empty_context: ToolContext,
    ) -> None:
        _add_task(empty_context, "A", status="pending", blocked_by=["B"], blocks=["B"])
        _add_task(empty_context, "B", status="pending", blocked_by=["A"], blocks=["A"])

        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "A", "status": "in_progress"},
        )
        _proposal, validation, _commit = service.run(change, empty_context)

        assert validation.result == "fail"
        issue = validation.issues[0]
        assert issue.code == "cyclic_dependency_blocks_readiness"
        assert set(issue.blockers) == {"A", "B"}
        assert any(s.action == "fix_cycle" for s in issue.repair_suggestions)
        assert any(s.action == "remove_dependency" for s in issue.repair_suggestions)
        assert any(s.action == "split_task" for s in issue.repair_suggestions)
        assert validation.counterexample is not None
        assert set(validation.counterexample.get("activeBlockers", [])) == {"A", "B"}


class TestAcceptanceProofRepair:
    def test_missing_acceptance_proof_suggests_adding_proof_or_keep_in_progress(
        self,
        service: LogicalKanbanService,
        empty_context: ToolContext,
    ) -> None:
        _add_task(empty_context, "T", status="in_progress")

        change = ProposedChange(
            kind="transition_status",
            payload={
                "taskId": "T",
                "status": "completed",
                "metadata": {"lkb": {"strict_acceptance": True}},
            },
        )
        _proposal, validation, _commit = service.run(change, empty_context)

        assert validation.result == "fail"
        issue = validation.issues[0]
        assert issue.code == "completed_requires_acceptance_proof"
        assert any(
            s.action == "add_acceptance_proof" and s.target == "T" for s in issue.repair_suggestions
        )
        assert any(
            s.action == "revalidate_task" and s.target == "T" for s in issue.repair_suggestions
        )


class TestToolOutputShape:
    def test_denied_task_update_includes_human_message_proof_trace_and_repair_suggestions(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
            "task"
        ]["id"]
        blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
            "task"
        ]["id"]
        TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

        result = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)

        assert result.is_error is True
        assert result.output["status"] == "denied"
        lkb = result.output["lkb"]
        assert lkb["decision"] == "denied"
        assert "humanMessage" in lkb
        assert lkb["humanMessage"]
        assert lkb["proofTrace"]
        assert lkb["repairSuggestions"]
        assert any(s["action"] == "complete_prerequisite" for s in lkb["repairSuggestions"])
        assert any(s["action"] == "remove_dependency" for s in lkb["repairSuggestions"])

    def test_accepted_task_update_includes_derived_facts_and_next_actions(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
            "id"
        ]

        result = TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

        assert result.is_error is False
        assert result.output["success"] is True
        lkb = result.output["lkb"]
        assert lkb["derivedFacts"]
        assert lkb["nextActions"]
        assert "complete_task" in lkb["nextActions"]


class TestTaskLkbView:
    def test_task_get_expanded_view_shows_explainability_fields(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
            "id"
        ]

        result = TaskGetTool.call({"taskId": task_id}, ctx)
        lkb = result.output["task"]["lkb"]

        assert "derivedStatus" in lkb
        assert "blockedReason" in lkb
        assert "latestValidationResult" in lkb
        assert "proofTraceSummary" in lkb
        assert "derivedFacts" in lkb
        assert "nextActions" in lkb

    def test_blocked_task_view_lists_blockers_and_repair_actions(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
            "task"
        ]["id"]
        blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
            "task"
        ]["id"]
        TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

        view = task_lkb_view(ctx, blocked, include_proof_trace=True)

        assert view["derivedStatus"] == "blocked"
        assert blocker in view["blockedBy"]
        assert blocker in (view["blockedReason"] or "")
        assert any(f"complete:{blocker}" in a for a in view["nextActions"])
        assert "remove_dependency" in view["nextActions"]
        assert "proofTraceSummary" in view

    def test_cycle_task_view_lists_cycle_tasks_and_fix_cycle_action(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        a = TaskCreateTool.call({"subject": "A", "description": "D1"}, ctx).output["task"]["id"]
        b = TaskCreateTool.call({"subject": "B", "description": "D2"}, ctx).output["task"]["id"]
        # Set up a mutual dependency cycle directly.
        ctx.tasks[a]["blockedBy"] = [b]
        ctx.tasks[a]["blocks"] = [b]
        ctx.tasks[b]["blockedBy"] = [a]
        ctx.tasks[b]["blocks"] = [a]

        view = task_lkb_view(ctx, a)

        assert view["derivedStatus"] in {"blocked", "needs_recheck"}
        assert b in view["blockedBy"]
        assert "fix_cycle" in view["nextActions"]
        assert "remove_dependency" in view["nextActions"]


class TestRepairSuggestionCanonicalActions:
    def test_all_repair_suggestions_use_canonical_f136_actions(
        self,
        service: LogicalKanbanService,
        empty_context: ToolContext,
    ) -> None:
        from clawcodex_ext.logical_kanban.types import RepairAction

        canonical = set(RepairAction.__args__)  # type: ignore[attr-defined]

        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "B", "status": "in_progress"},
        )
        _proposal, validation, _commit = service.run(change, empty_context)

        for issue in validation.issues:
            for suggestion in issue.repair_suggestions:
                assert suggestion.action in canonical

    def test_repair_suggestion_priority_is_populated(
        self,
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

        priorities = {s.priority for s in validation.issues[0].repair_suggestions}
        assert priorities
        assert all(isinstance(p, int) and p > 0 for p in priorities)


def test_repair_suggestion_to_dict_hides_defaults() -> None:
    suggestion = RepairSuggestion(action="complete_prerequisite", target="T")
    assert suggestion.to_dict() == {"action": "complete_prerequisite", "target": "T"}

    suggestion_with_priority = RepairSuggestion(
        action="add_acceptance_proof", target="T", priority=2
    )
    assert suggestion_with_priority.to_dict()["priority"] == 2
