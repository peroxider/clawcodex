from __future__ import annotations

from pathlib import Path

from src.tool_system.context import ToolContext
from src.tool_system.tools import TaskCreateTool, TaskUpdateTool, TodoWriteTool


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
