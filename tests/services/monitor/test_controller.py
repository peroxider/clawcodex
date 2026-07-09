"""Tests for F-88 MonitorController."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from clawcodex_ext.services.monitor.controller import MonitorController
from clawcodex_ext.tool_system.context import ToolContext
from src.tasks.local_shell import LocalShellTaskState


@pytest.fixture
def tool_context():
    return ToolContext(workspace_root=Path(tempfile.gettempdir()))


class TestMonitorController:
    def test_start_tags_kind_monitor(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "echo hello"', description="test")
        assert result.kind == "monitor"
        state = tool_context.runtime_tasks.get(result.task_id)
        assert isinstance(state, LocalShellTaskState)
        assert state.kind == "monitor"
        assert state.description == "test"
        ctrl.stop(result.task_id)

    def test_start_with_interval(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(
            command='bash -c "echo tick"',
            interval_sec=5,
        )
        state = tool_context.runtime_tasks.get(result.task_id)
        assert state.interval_sec == 5
        ctrl.stop(result.task_id)

    def test_list_active_only_running_monitors(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "sleep 0.5; echo done"')
        active = ctrl.list_active()
        assert any(t.id == result.task_id for t in active)
        # After stopping, the task should disappear from active.
        ctrl.stop(result.task_id)
        # Wait briefly for the reaper to update status.
        for _ in range(20):
            if not any(t.id == result.task_id for t in ctrl.list_active()):
                break
            asyncio.run(asyncio.sleep(0.05))
        assert not any(t.id == result.task_id for t in ctrl.list_active())

    def test_stop_existing_task(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "sleep 5"')
        assert ctrl.stop(result.task_id) is True

    def test_stop_unknown_task(self, tool_context):
        ctrl = MonitorController(tool_context)
        assert ctrl.stop("bunknown1") is False

    def test_read_snapshot(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "echo hello"')
        # Wait for the command to finish.
        for _ in range(50):
            snap = ctrl.read(result.task_id)
            if snap and snap.get("status") in ("completed", "failed"):
                break
            asyncio.run(asyncio.sleep(0.05))
        snap = ctrl.read(result.task_id)
        assert snap is not None
        assert "hello" in snap["output"]
        ctrl.stop(result.task_id)

    def test_tail_returns_follower(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "echo hello"')
        follower = ctrl.tail(result.task_id, max_bytes=1000)
        assert follower is not None
        assert follower.current_tail == ""
        ctrl.stop(result.task_id)

    def test_legacy_dict_tagged(self, tool_context):
        ctrl = MonitorController(tool_context)
        result = ctrl.start(command='bash -c "echo hello"', interval_sec=2)
        legacy = tool_context.background_bash_tasks.get(result.task_id)
        assert legacy["kind"] == "monitor"
        assert legacy["interval_sec"] == 2
        ctrl.stop(result.task_id)
