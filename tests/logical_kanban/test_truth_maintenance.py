"""Tests for F-135 Truth Maintenance System."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.logical_kanban import (
    Assumption,
    Clarification,
    LogicalKanbanService,
    ProposedChange,
    TruthMaintenanceSystem,
)
from clawcodex_ext.logical_kanban.context_adapter import task_lkb_view
from clawcodex_ext.logical_kanban.fuzzy_types import AssumptionSource
from clawcodex_ext.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool


def _set_lkb(monkeypatch, enabled: bool) -> None:
    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


@pytest.fixture
def tms() -> TruthMaintenanceSystem:
    return TruthMaintenanceSystem()


def _make_assumption(
    assumption_id: str = "H-001",
    assertion_id: str = "A-001",
    field: str = "resource_available",
    value: Any = True,
    confidence: float = 0.85,
    source: AssumptionSource = "default_kb",
) -> Assumption:
    return Assumption(
        assumption_id=assumption_id,
        assertion_id=assertion_id,
        field=field,
        assumed_value=str(value),
        confidence=confidence,
        source=source,
    )


class TestTruthMaintenanceSystem:
    def test_register_assertion_imports_assumptions(self, tms: TruthMaintenanceSystem) -> None:
        assumption = _make_assumption()
        record = tms.register_assertion(
            "A-001",
            assumptions=(assumption,),
            task_ids=("T-001",),
        )

        assert record.assertion_id == "A-001"
        assert record.assumption_ids == {"H-001"}
        assert record.task_ids == {"T-001"}
        assert tms.get_assumption("H-001") is not None

    def test_invalidate_assumption_marks_dependent_assertion_stale(
        self, tms: TruthMaintenanceSystem
    ) -> None:
        assumption = _make_assumption()
        tms.register_assertion("A-001", assumptions=(assumption,), task_ids=("T-001",))

        tms.invalidate_assumption("H-001", "user refuted")

        record = tms.get_assumption("H-001")
        assert record is not None
        assert record.status == "invalid"
        assert tms.is_assertion_stale("A-001")
        assert tms.is_task_affected("T-001")
        assert tms.get_stale_task_ids() == {"T-001"}

    def test_stale_propagates_to_derived_assertions(self, tms: TruthMaintenanceSystem) -> None:
        assumption = _make_assumption()
        tms.register_assertion("A-001", assumptions=(assumption,))
        tms.register_derived_fact("D-001", derived_from=("A-001",), task_ids=("T-001",))
        tms.register_derived_fact("D-002", derived_from=("D-001",), task_ids=("T-001",))

        tms.invalidate_assumption("H-001")

        assert tms.is_assertion_stale("A-001")
        assert tms.is_assertion_stale("D-001")
        assert tms.is_assertion_stale("D-002")

    def test_clarify_confirm_clears_stale(self, tms: TruthMaintenanceSystem) -> None:
        assumption = _make_assumption()
        tms.register_assertion("A-001", assumptions=(assumption,), task_ids=("T-001",))
        tms.invalidate_assumption("H-001")
        assert tms.is_assertion_stale("A-001")

        new, old = tms.clarify_assumption(
            "H-001",
            Clarification(assumption_id="H-001", action="confirm", new_value="true"),
        )

        assert old is None
        assert new.status == "active"
        assert new.confidence == 1.0
        assert new.source == "user_clarified"
        assert not tms.is_assertion_stale("A-001")

    def test_clarify_override_creates_new_assumption(
        self, tms: TruthMaintenanceSystem
    ) -> None:
        assumption = _make_assumption()
        tms.register_assertion("A-001", assumptions=(assumption,), task_ids=("T-001",))
        tms.invalidate_assumption("H-001")

        new, old = tms.clarify_assumption(
            "H-001",
            Clarification(assumption_id="H-001", action="override", new_value="false"),
        )

        assert old is not None
        assert old.status == "superseded"
        assert new.assumption_id != old.assumption_id
        assert new.status == "active"
        assert new.value == "false"
        assert not tms.is_assertion_stale("A-001")


class TestServiceIntegration:
    def test_stale_assumption_blocks_status_transition(self, tmp_path: Path, monkeypatch) -> None:
        _set_lkb(monkeypatch, True)
        service = LogicalKanbanService()
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call(
            {"subject": "Task", "description": "D"}, ctx
        ).output["task"]["id"]

        # Register an assumption linked to the task.
        service._register_assertion_in_tms(
            ctx,
            assertion_id="A-001",
            worlds=(
                type("W", (), {"assumptions": (_make_assumption(),)})(),
            ),
            target_task_id=task_id,
        )
        service._tms(ctx).invalidate_assumption("H-001")

        proposal = service.propose(
            ProposedChange(kind="transition_status", payload={"taskId": task_id, "status": "in_progress"}),
            ctx,
        )
        validation = service.validate(proposal, ctx)

        assert validation.result == "stale"
        assert validation.issues[0].code == "stale_assumption_blocks_transition"

    def test_clarification_triggers_new_validation_run(self, tmp_path: Path, monkeypatch) -> None:
        _set_lkb(monkeypatch, True)
        service = LogicalKanbanService()
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call(
            {"subject": "Task", "description": "D"}, ctx
        ).output["task"]["id"]

        service._register_assertion_in_tms(
            ctx,
            assertion_id="A-001",
            worlds=(
                type("W", (), {"assumptions": (_make_assumption(),)})(),
            ),
            target_task_id=task_id,
        )
        service._tms(ctx).invalidate_assumption("H-001")

        new_record, _old_record, validation_run = service.clarify_assumption(
            ctx,
            "H-001",
            Clarification(assumption_id="H-001", action="confirm", new_value="true"),
        )

        assert validation_run is not None
        assert validation_run.result == "pass"
        assert validation_run.task_id == task_id


class TestTaskViews:
    def test_stale_task_surfaces_as_needs_recheck(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _set_lkb(monkeypatch, True)
        service = LogicalKanbanService()
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call(
            {"subject": "Task", "description": "D"}, ctx
        ).output["task"]["id"]

        service._register_assertion_in_tms(
            ctx,
            assertion_id="A-001",
            worlds=(
                type("W", (), {"assumptions": (_make_assumption(),)})(),
            ),
            target_task_id=task_id,
        )
        service._tms(ctx).invalidate_assumption("H-001")

        view = task_lkb_view(ctx, task_id)

        assert view["derivedStatus"] == "needs_recheck"
        assert "H-001" in view["blockedReason"]
        assert view["nextActions"] == ["clarify_assumption"]
        assert view["staleAssumptions"]

    def test_task_list_includes_needs_recheck(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _set_lkb(monkeypatch, True)
        service = LogicalKanbanService()
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call(
            {"subject": "Task", "description": "D"}, ctx
        ).output["task"]["id"]

        service._register_assertion_in_tms(
            ctx,
            assertion_id="A-001",
            worlds=(
                type("W", (), {"assumptions": (_make_assumption(),)})(),
            ),
            target_task_id=task_id,
        )
        service._tms(ctx).invalidate_assumption("H-001")

        tasks = TaskListTool.call({}, ctx).output["tasks"]
        row = next(t for t in tasks if t["id"] == task_id)

        assert row["lkb"]["derivedStatus"] == "needs_recheck"


class TestTaskToolClarification:
    def test_task_update_assumption_clarification_triggers_revalidation(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _set_lkb(monkeypatch, True)
        service = LogicalKanbanService()
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call(
            {"subject": "Task", "description": "D"}, ctx
        ).output["task"]["id"]

        service._register_assertion_in_tms(
            ctx,
            assertion_id="A-001",
            worlds=(
                type("W", (), {"assumptions": (_make_assumption(),)})(),
            ),
            target_task_id=task_id,
        )
        service._tms(ctx).invalidate_assumption("H-001")

        # Initially the task is stale.
        assert task_lkb_view(ctx, task_id)["derivedStatus"] == "needs_recheck"

        # Submit a clarification through task metadata.
        result = TaskUpdateTool.call(
            {
                "taskId": task_id,
                "metadata": {
                    "lkb": {
                        "assumption_clarifications": [
                            {
                                "assumption_id": "H-001",
                                "action": "confirm",
                                "new_value": "true",
                            }
                        ]
                    }
                },
            },
            ctx,
        )

        assert result.is_error is False
        assert result.output["assumptionClarificationsApplied"]
        assert result.output["assumptionClarificationsApplied"][0]["validationRunId"]
        assert task_lkb_view(ctx, task_id)["derivedStatus"] == "ready"
