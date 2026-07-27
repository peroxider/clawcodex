from __future__ import annotations

from pathlib import Path

import pytest

from clawcodex_ext.command_system.types import LocalCommandResult
from clawcodex_ext.feature_gate import get_registry
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.defaults import build_default_registry
from clawcodex_ext.tool_system.tools.tasks_v2 import TaskCreateTool
from lkb.clawcodex_tool import _lkb_tool_call


def test_default_registry_exposes_agent_callable_lkb_board(
    tmp_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TASKS", "1")
    monkeypatch.setenv("CLAWCODEX_FEATURE_LKB_PLAN_GRAPH", "1")
    get_registry()._overrides["LKB_PLAN_GRAPH"] = True
    context = ToolContext(workspace_root=tmp_path)

    created = TaskCreateTool.call(
        {"subject": "Visible from Lkb tool", "description": "panel test"},
        context,
    )
    task_id = created.output["task"]["id"]

    registry = build_default_registry(provider=object(), load_agent_tools=False)
    tool = registry.get("Lkb")
    assert tool is not None
    assert tool.is_enabled() is True
    result = tool.call({"action": "board", "compact": True}, context)

    assert result.name == "Lkb"
    assert result.output["command"] == "/lkb board --compact"
    assert "LKB BOARD:" in result.output["text"]
    assert task_id in result.output["text"]


def test_agent_callable_lkb_marks_board_resolution_failure_as_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_board_resolution(_args: str, _context: object) -> LocalCommandResult:
        return LocalCommandResult(
            type="text",
            value="No LKB board found for this workspace: incompatible repository API",
        )

    monkeypatch.setattr("lkb.clawcodex_commands._lkb_call", fail_board_resolution)
    result = _lkb_tool_call({"action": "status"}, ToolContext(workspace_root=tmp_path))

    assert result.is_error is True
    assert result.output["success"] is False
