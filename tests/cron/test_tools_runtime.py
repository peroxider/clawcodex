from __future__ import annotations

import pytest

from clawcodex_ext.cron_system.runs import read_cron_runs
from clawcodex_ext.cron_system.runtime import (attach_cron_runtime,
                                               replace_cron_tools)
from clawcodex_ext.cron_system.tools import CronCreateTool
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


def test_extension_tools_store_session_tasks_by_default(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call({"cron": "*/5 * * * *", "prompt": "ping"}, ctx).output
    assert len(created["id"]) == 8
    assert created["durable"] is False
    listed = registry_tool("CronList").call({}, ctx).output
    assert [job["id"] for job in listed["jobs"]] == [created["id"]]
    assert not (tmp_path / ".claude" / "scheduled_tasks.json").exists()
    deleted = registry_tool("CronDelete").call({"id": created["id"]}, ctx).output
    assert deleted["success"] is True


def test_extension_tools_persist_durable_tasks(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "ping", "durable": True}, ctx
    ).output
    assert created["durable"] is True
    assert (tmp_path / ".claude" / "scheduled_tasks.json").exists()
    listed = registry_tool("CronList").call({}, ctx).output
    assert [job["id"] for job in listed["jobs"]] == [created["id"]]


def test_extension_delete_missing_task_errors(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    with pytest.raises(ToolInputError, match="No scheduled job"):
        registry_tool("CronDelete").call({"id": "missing"}, ctx)


def test_mutating_cron_tools_are_not_read_only() -> None:
    assert CronCreateTool.is_read_only({}) is False
    assert registry_tool("CronDelete").is_read_only({}) is False
    assert registry_tool("CronList").is_read_only({}) is True


# ---------------------------------------------------------------------------
# Phase D-3: dual-durable coverage at the tool-API level.
# ---------------------------------------------------------------------------


def test_durable_false_and_true_both_visible_in_list(tmp_path) -> None:
    ctx = ToolContext(workspace_root=tmp_path)
    session = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "session"}, ctx
    ).output
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
    created = CronCreateTool.call(
        {"cron": "*/5 * * * *", "prompt": "session"}, ctx
    ).output
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
    assert not (tmp_path / ".claude" / "scheduled_tasks.json").exists()
    # but they must be visible in the session store
    assert "crons" in dir(ctx) or hasattr(ctx, "crons")
    assert any(t.prompt == "session" for t in ctx.crons.values())


def registry_tool(name: str):
    registry = build_default_registry(provider=None)
    replace_cron_tools(registry)
    tool = registry.get(name)
    assert tool is not None
    return tool
