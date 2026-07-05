from __future__ import annotations

from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskListTool, TaskUpdateTool, TodoWriteTool


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
    assert result.output["reason"]["code"] == "blocked_task_cannot_enter_in_progress"
    assert result.output["logicalKanban"]["validation"]["status"] == "denied"
    assert ctx.tasks[blocked]["status"] == "pending"


def test_feature_on_allows_unblocked_task_status_write(
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
    assert ctx.tasks[task_id]["status"] == "in_progress"


def test_context_adapter_derives_blocked_and_ready_without_mutating_context(
    tmp_path: Path,
) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
        "task"
    ]["id"]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
        "task"
    ]["id"]
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


def test_context_adapter_repairs_blocks_blocked_by_mismatch_for_task_list(
    tmp_path: Path,
) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
        "task"
    ]["id"]
    blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
        "task"
    ]["id"]
    TaskUpdateTool.call({"taskId": blocker, "addBlocks": [blocked]}, ctx)

    snapshot = build_facts_snapshot(ctx)
    listed = TaskListTool.call({}, ctx).output["tasks"]
    blocked_entry = [task for task in listed if task["id"] == blocked][0]

    assert f"Blocks({blocker}, {blocked})" in snapshot.facts
    assert f"Requires({blocker}, {blocked})" in snapshot.facts
    assert blocked_entry["blockedBy"] == [blocker]
    assert [warning.code for warning in snapshot.warnings] == [
        "dependency_direction_mismatch"
    ]


def test_context_adapter_reports_dangling_blockers_as_warnings(tmp_path: Path) -> None:
    from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot

    ctx = ToolContext(workspace_root=tmp_path)
    task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
        "id"
    ]
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
    first = TaskCreateTool.call({"subject": "First", "description": "D1"}, ctx).output[
        "task"
    ]["id"]
    second = TaskCreateTool.call({"subject": "Second", "description": "D2"}, ctx).output[
        "task"
    ]["id"]
    TaskUpdateTool.call({"taskId": first, "addBlockedBy": [second]}, ctx)
    TaskUpdateTool.call({"taskId": second, "addBlockedBy": [first]}, ctx)

    result = TaskUpdateTool.call({"taskId": first, "status": "in_progress"}, ctx)

    assert result.is_error is True
    assert result.output["reason"]["code"] == "cyclic_dependency_blocks_readiness"
    assert ctx.tasks[first]["status"] == "pending"
