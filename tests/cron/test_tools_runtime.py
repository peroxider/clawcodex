from __future__ import annotations

import pytest

from clawcodex_ext.cron_system.runs import read_cron_runs
from clawcodex_ext.cron_system.runtime import attach_cron_runtime, replace_cron_tools
from clawcodex_ext.cron_system.tools import CronCreateTool, CronRunTool
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.errors import ToolInputError
from src.tool_system.tools.cron import CronCreateTool as FallbackCronCreateTool


class _Runtime:
    def __init__(self, tmp_path):
        self.workspace_root = tmp_path
        self.tool_context = ToolContext(workspace_root=tmp_path)


def test_replace_cron_tools_swaps_fallback_implementation() -> None:
    registry = build_default_registry(provider=None)
    assert registry.get("CronCreate") is FallbackCronCreateTool
    replace_cron_tools(registry)
    assert registry.get("CronCreate") is CronCreateTool
    assert registry.get("CronRun") is CronRunTool


def test_extension_tools_store_session_tasks_by_default(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call({"cron": "*/5 * * * *", "prompt": "ping"}, ctx).output
    assert len(created["id"]) == 8
    assert created["durable"] is False
    listed = registry_tool("CronList").call({}, ctx).output
    assert [job["id"] for job in listed["jobs"]] == [created["id"]]
    assert not (tmp_path / ".clawcodex" / "cron" / "scheduled_tasks.json").exists()
    deleted = registry_tool("CronDelete").call({"id": created["id"]}, ctx).output
    assert deleted["success"] is True


def test_extension_tools_persist_durable_tasks(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "ping", "durable": True}, ctx
    ).output
    assert created["durable"] is True
    assert (tmp_path / ".clawcodex" / "cron" / "scheduled_tasks.json").exists()
    listed = registry_tool("CronList").call({}, ctx).output
    assert [job["id"] for job in listed["jobs"]] == [created["id"]]


def test_extension_delete_missing_task_errors(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    with pytest.raises(ToolInputError, match="No scheduled job"):
        registry_tool("CronDelete").call({"id": "missing"}, ctx)


def test_mutating_cron_tools_are_not_read_only() -> None:
    assert CronCreateTool.is_read_only({}) is False
    assert registry_tool("CronDelete").is_read_only({}) is False
    assert registry_tool("CronRun").is_read_only({}) is False
    assert registry_tool("CronList").is_read_only({}) is True


def test_cron_run_tool_creates_queued_run(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "manual ping", "durable": True},
        ctx,
    ).output

    result = registry_tool("CronRun").call({"id": created["id"]}, ctx).output

    assert result["success"] is True
    assert result["id"] == created["id"]
    assert result["run"]["task_id"] == created["id"]
    assert result["run"]["prompt"] == "manual ping"
    assert result["run"]["status"] == "queued"
    runs = read_cron_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0].id == result["run"]["id"]


def test_cron_run_tool_blocks_duplicate_active_run(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "manual ping", "durable": True},
        ctx,
    ).output
    run_tool = registry_tool("CronRun")

    first = run_tool.call({"id": created["id"]}, ctx).output
    second = run_tool.call({"id": created["id"]}, ctx).output

    assert first["success"] is True
    assert second == {"success": False, "id": created["id"], "run": None}
    assert len(read_cron_runs(tmp_path)) == 1


def test_cron_run_tool_reports_missing_task(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)

    result = registry_tool("CronRun").call({"id": "missing"}, ctx).output

    assert result == {"success": False, "id": "missing", "not_found": True}
    assert read_cron_runs(tmp_path) == []


def test_cron_run_tool_respects_kill_switch(tmp_path, monkeypatch) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "manual ping", "durable": True},
        ctx,
    ).output

    monkeypatch.setenv("CLAWCODEX_DISABLE_CRON", "1")
    result = registry_tool("CronRun").call({"id": created["id"]}, ctx).output

    assert result["disabled"] is True
    assert read_cron_runs(tmp_path) == []


# ---------------------------------------------------------------------------
# Phase D-3: dual-durable coverage at the tool-API level.
# ---------------------------------------------------------------------------


def test_durable_false_and_true_both_visible_in_list(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    session = CronCreateTool.call({"cron": "*/5 * * * *", "prompt": "session"}, ctx).output
    durable = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "durable", "durable": True}, ctx
    ).output
    assert session["durable"] is False
    assert durable["durable"] is True
    listed = registry_tool("CronList").call({}, ctx).output
    prompts = {job["prompt"] for job in listed["jobs"]}
    assert {"session", "durable"} <= prompts


def test_durable_false_delete_works(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call({"cron": "*/5 * * * *", "prompt": "session"}, ctx).output
    # Session tasks live in ctx.crons (in-memory). CronDelete must find
    # them there since the file is never written.
    deleted = registry_tool("CronDelete").call({"id": created["id"]}, ctx).output
    assert deleted["success"] is True
    listed = registry_tool("CronList").call({}, ctx).output
    assert listed["jobs"] == []


def test_durable_false_path_not_written_to_disk(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    CronCreateTool.call({"cron": "*/5 * * * *", "prompt": "session"}, ctx)
    # durable=False tasks must NOT touch the persisted file
    assert not (tmp_path / ".clawcodex" / "cron" / "scheduled_tasks.json").exists()
    # but they must be visible in the session store
    assert "crons" in dir(ctx) or hasattr(ctx, "crons")
    assert any(t.prompt == "session" for t in ctx.crons.values())


def registry_tool(name: str):
    registry = build_default_registry(provider=None)
    replace_cron_tools(registry)
    tool = registry.get(name)
    assert tool is not None
    return tool
