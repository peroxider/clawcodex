from __future__ import annotations

from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.tools import (
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskUpdateTool,
    TodoWriteTool,
)


def _set_lkb(monkeypatch, enabled: bool) -> None:
    from clawcodex_ext.feature_gate import get_registry

    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


def test_tool_context_can_hold_lkb_runtime(tmp_path: Path) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    ctx = ToolContext(workspace_root=tmp_path)
    runtime = get_logical_kanban(ctx)

    assert ctx.logical_kanban is runtime
    assert runtime.service.snapshot(ctx).hash.startswith("sha256:")


def test_feature_off_preserves_todowrite_output(tmp_path: Path, monkeypatch) -> None:
    _set_lkb(monkeypatch, False)
    ctx = ToolContext(workspace_root=tmp_path)

    out = TodoWriteTool.call(
        {"todos": [{"content": "x", "status": "pending", "activeForm": "Doing x"}]},
        ctx,
    ).output

    assert out == {
        "oldTodos": [],
        "newTodos": [{"content": "x", "status": "pending", "activeForm": "Doing x"}],
    }
    assert ctx.todos == [{"content": "x", "status": "pending", "activeForm": "Doing x"}]


def test_feature_on_denies_blocked_task_status_write(
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
    assert result.output["reason"]["code"] == "blocked_task_cannot_enter_in_progress"
    assert result.output["lkb"]["decision"] == "denied"
    assert ctx.tasks[blocked]["status"] == "pending"


def test_feature_on_allows_unblocked_task_status_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"]["id"]

    result = TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

    assert result.is_error is False
    assert result.output["success"] is True
    assert result.output["lkb"]["validationRunId"].startswith("V-")
    assert result.output["lkb"]["decision"] == "committed"
    assert ctx.tasks[task_id]["status"] == "in_progress"
    assert (
        ctx.tasks[task_id]["metadata"]["lkb"]["validation_run_id"]
        == result.output["lkb"]["validationRunId"]
    )


def test_feature_on_task_create_emits_structural_facts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)

    result = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx)
    task_id = result.output["task"]["id"]

    assert result.output["lkb"]["validationRunId"].startswith("V-")
    assert result.output["lkb"]["createdFacts"] == [
        f"Task({task_id})",
        f"Pending({task_id})",
        f"Status({task_id}, pending)",
    ]
    assert ctx.tasks[task_id]["metadata"]["lkb"]["validation_run_id"].startswith("V-")


def test_feature_on_rejects_invalid_lkb_metadata_shape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)

    try:
        TaskCreateTool.call(
            {"subject": "Task", "description": "D", "metadata": {"lkb": "invalid"}},
            ctx,
        )
    except Exception as exc:
        assert "metadata.lkb must be an object" in str(exc)
    else:
        raise AssertionError("TaskCreate should reject invalid metadata.lkb")


def test_feature_on_denied_mixed_update_does_not_mutate_any_task_fields(
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
    before = dict(ctx.tasks[blocked])

    result = TaskUpdateTool.call(
        {
            "taskId": blocked,
            "subject": "Should not land",
            "status": "in_progress",
            "metadata": {"note": "should not land"},
        },
        ctx,
    )

    assert result.is_error is True
    assert result.output["lkb"]["decision"] == "denied"
    assert result.output["lkb"]["validationRunId"].startswith("V-")
    assert ctx.tasks[blocked] == before


def test_feature_on_task_get_list_and_output_expose_lkb_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import asyncio

    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output["task"][
        "id"
    ]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output["task"][
        "id"
    ]
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

    denied = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)
    got = TaskGetTool.call({"taskId": blocked}, ctx).output["task"]
    listed = TaskListTool.call({}, ctx).output["tasks"]
    listed_blocked = [task for task in listed if task["id"] == blocked][0]
    task_output = asyncio.run(TaskOutputTool.call({"task_id": blocked}, ctx)).output["task"]

    assert got["status"] == "pending"
    assert got["lkb"]["derivedStatus"] == "blocked"
    assert got["lkb"]["blockedBy"] == [blocker]
    assert (
        got["lkb"]["latestDenialReason"]["validationRunId"]
        == denied.output["lkb"]["validationRunId"]
    )
    assert listed_blocked["blockedBy"] == [blocker]
    assert listed_blocked["lkb"]["blockedReason"] == f"Blocked by incomplete task(s): {blocker}."
    assert task_output["lkb"]["validation_status"] == "denied"
    assert task_output["lkb"]["blocked_reason"] == f"Blocked by incomplete task(s): {blocker}."


def test_feature_on_completing_blocker_then_retrying_blocked_task_succeeds(
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

    denied = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)
    TaskUpdateTool.call({"taskId": blocker, "status": "completed"}, ctx)
    retried = TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)

    assert denied.is_error is True
    assert retried.is_error is False
    assert ctx.tasks[blocked]["status"] == "in_progress"


def test_feature_on_strict_acceptance_denies_completion_without_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    get_logical_kanban(ctx).strict_acceptance_enabled = True
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"]["id"]
    TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

    result = TaskUpdateTool.call({"taskId": task_id, "status": "completed"}, ctx)

    assert result.is_error is True
    assert result.output["reason"]["code"] == "completed_requires_acceptance_proof"
    assert ctx.tasks[task_id]["status"] == "in_progress"


def test_feature_on_strict_acceptance_allows_completion_with_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    get_logical_kanban(ctx).strict_acceptance_enabled = True
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"]["id"]
    TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

    result = TaskUpdateTool.call(
        {
            "taskId": task_id,
            "status": "completed",
            "metadata": {"lkb": {"acceptance_proof": "tests passed"}},
        },
        ctx,
    )

    assert result.is_error is False
    assert result.output["lkb"]["validationRunId"].startswith("V-")
    assert "HasAcceptanceProof" in " ".join(result.output["lkb"]["derivedFacts"])
    assert ctx.tasks[task_id]["status"] == "completed"


def test_context_adapter_derives_blocked_and_ready_without_mutating_context(
    tmp_path: Path,
) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output["task"][
        "id"
    ]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output["task"][
        "id"
    ]
    TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

    before = {task_id: dict(task) for task_id, task in ctx.tasks.items()}
    snapshot = build_facts_snapshot(ctx)

    assert f"Requires({blocker}, {blocked})" in snapshot.facts
    assert blocked in snapshot.blocked_ids
    assert blocked not in snapshot.ready_ids
    assert ctx.tasks == before

    TaskUpdateTool.call({"taskId": blocker, "status": "completed"}, ctx)
    snapshot = build_facts_snapshot(ctx)

    assert blocked not in snapshot.blocked_ids
    assert blocked in snapshot.ready_ids


def test_feature_on_delete_cascades_only_after_validation(
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

    missing = TaskUpdateTool.call({"taskId": "missing", "status": "deleted"}, ctx)
    assert missing.output["success"] is False
    assert blocker in ctx.tasks[blocked]["blockedBy"]

    deleted = TaskUpdateTool.call({"taskId": blocker, "status": "deleted"}, ctx)
    assert deleted.output["success"] is True
    assert deleted.output["lkb"]["validationRunId"].startswith("V-")
    assert blocker not in ctx.tasks
    assert blocker not in ctx.tasks[blocked]["blockedBy"]


def test_feature_on_todo_write_success_includes_lkb_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)

    result = TodoWriteTool.call(
        {"todos": [{"content": "x", "status": "pending", "activeForm": "Doing x"}]},
        ctx,
    )

    assert result.output["lkb"]["changeKind"] == "legacy_todo_replace_all"
    assert result.output["lkb"]["compatibilityMode"] == "legacy_todo_write"
    assert result.output["lkb"]["progress"] == {
        "total": 1,
        "pending": 1,
        "in_progress": 0,
        "completed": 0,
    }
    assert result.output["lkb"]["validationRunId"].startswith("V-")
    assert ctx.todos == [{"content": "x", "status": "pending", "activeForm": "Doing x"}]


def test_feature_on_todo_write_all_completed_still_clears_context_todos(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    ctx.todos = [{"content": "old", "status": "pending", "activeForm": "Doing old"}]

    result = TodoWriteTool.call(
        {"todos": [{"content": "x", "status": "completed", "activeForm": "Did x"}]},
        ctx,
    )

    assert result.is_error is False
    assert result.output["lkb"]["compatibilityMode"] == "legacy_todo_write"
    assert "AllLegacyTodosCompleted" in result.output["lkb"]["derivedFacts"]
    assert ctx.todos == []
    assert ctx.tasks == {}


def test_feature_on_legacy_todo_write_allows_multiple_in_progress_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)

    result = TodoWriteTool.call(
        {
            "todos": [
                {"content": "a", "status": "in_progress", "activeForm": "Doing a"},
                {"content": "b", "status": "in_progress", "activeForm": "Doing b"},
            ]
        },
        ctx,
    )

    assert result.is_error is False
    assert result.output["lkb"]["progress"]["in_progress"] == 2
    assert [todo["status"] for todo in ctx.todos] == ["in_progress", "in_progress"]
    assert ctx.tasks == {}


def test_feature_on_strict_legacy_todo_write_denies_multiple_in_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from clawcodex_ext.logical_kanban import get_logical_kanban

    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    get_logical_kanban(ctx).strict_logical_todo_enabled = True
    ctx.todos = [{"content": "old", "status": "pending", "activeForm": "Doing old"}]

    result = TodoWriteTool.call(
        {
            "todos": [
                {"content": "a", "status": "in_progress", "activeForm": "Doing a"},
                {"content": "b", "status": "in_progress", "activeForm": "Doing b"},
            ]
        },
        ctx,
    )

    assert result.is_error is True
    assert result.output["reason"]["code"] == "multiple_in_progress_legacy_todo_write"
    assert result.output["lkb"]["compatibilityMode"] == "legacy_todo_write"
    assert result.output["lkb"]["progress"]["in_progress"] == 2
    assert ctx.todos == [{"content": "old", "status": "pending", "activeForm": "Doing old"}]
    assert ctx.tasks == {}


def test_context_adapter_repairs_blocks_blocked_by_mismatch_for_task_list(
    tmp_path: Path,
) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output["task"][
        "id"
    ]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output["task"][
        "id"
    ]
    TaskUpdateTool.call({"taskId": blocker, "addBlocks": [blocked]}, ctx)

    snapshot = build_facts_snapshot(ctx)
    listed = TaskListTool.call({}, ctx).output["tasks"]
    blocked_entry = [task for task in listed if task["id"] == blocked][0]

    assert f"Blocks({blocker}, {blocked})" in snapshot.facts
    assert f"Requires({blocker}, {blocked})" in snapshot.facts
    assert blocked_entry["blockedBy"] == [blocker]
    assert [warning.code for warning in snapshot.warnings] == ["dependency_direction_mismatch"]


def test_context_adapter_reports_dangling_blockers_as_warnings(tmp_path: Path) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"]["id"]
    TaskUpdateTool.call({"taskId": task_id, "addBlockedBy": ["missing"]}, ctx)

    snapshot = build_facts_snapshot(ctx)

    assert snapshot.warnings
    assert snapshot.warnings[0].code == "dangling_blocker"
    assert snapshot.warnings[0].severity == "warning"
    assert "missing" not in snapshot.blocked_by[task_id]


def test_context_adapter_maps_todos_with_deterministic_call_order_ids(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    _set_lkb(monkeypatch, False)
    ctx = ToolContext(workspace_root=tmp_path)
    TodoWriteTool.call(
        {
            "todos": [
                {"content": "First todo", "status": "pending", "activeForm": "Doing first"},
                {
                    "content": "Second todo",
                    "status": "in_progress",
                    "activeForm": "Doing second",
                },
            ]
        },
        ctx,
    )

    snapshot = build_facts_snapshot(ctx)

    assert "Task(todo:0)" in snapshot.facts
    assert "Status(todo:0, pending)" in snapshot.facts
    assert 'Title(todo:0, "First todo")' in snapshot.facts
    assert "Task(todo:1)" in snapshot.facts
    assert "Status(todo:1, in_progress)" in snapshot.facts


def test_feature_on_denies_cyclic_readiness_transition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _set_lkb(monkeypatch, True)
    ctx = ToolContext(workspace_root=tmp_path)
    first = TaskCreateTool.call({"subject": "First", "description": "D1"}, ctx).output["task"]["id"]
    second = TaskCreateTool.call({"subject": "Second", "description": "D2"}, ctx).output["task"][
        "id"
    ]
    TaskUpdateTool.call({"taskId": first, "addBlockedBy": [second]}, ctx)
    reciprocal = TaskUpdateTool.call({"taskId": second, "addBlockedBy": [first]}, ctx)

    result = TaskUpdateTool.call({"taskId": first, "status": "in_progress"}, ctx)

    assert reciprocal.is_error is True
    assert reciprocal.output["reason"]["code"] == "dependency_cycle_denied"
    assert result.is_error is True
    assert result.output["reason"]["code"] == "blocked_task_cannot_enter_in_progress"
    assert ctx.tasks[first]["status"] == "pending"
