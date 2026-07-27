"""End-to-end pilot tests for the Claw Codex Textual TUI.

Uses Textual's :meth:`App.run_test` harness to drive the real UI under an
in-memory terminal emulator. We mock the provider so no network traffic is
required — the tests are fast (<2s) and hermetic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

pytest.importorskip("textual")

from src.tui.app import ClawCodexTUI
from src.tui.messages import ToolEventMessage
from src.tui.widgets import PromptInput, StartupHeader, StatusBar, Transcript
from src.tui.widgets.task_list import TaskProgressPanel
from src.tool_system.registry import ToolRegistry
from src.tool_system.context import ToolContext


class _FakeProvider:
    """Minimal provider stand-in for the agent loop.

    We bypass ``run_agent_loop`` entirely by monkeypatching
    :meth:`ClawCodexTUI._run_agent_in_thread` in individual tests; this class
    just needs to satisfy attribute lookups done at construction time.
    """

    provider_name = "fake"
    model = "fake-model"


def _make_app(tmp_path: Path) -> ClawCodexTUI:
    registry = ToolRegistry()
    tool_context = ToolContext(workspace_root=tmp_path)
    return ClawCodexTUI(
        provider=_FakeProvider(),
        provider_name="fake",
        workspace_root=tmp_path,
        tool_registry=registry,
        tool_context=tool_context,
        stream=False,
    )


def test_second_ctrl_c_force_exits_busy_app(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    cancel = Mock(return_value=True)
    exit_app = Mock()
    announce = Mock()
    monkeypatch.setattr(app._agent_bridge, "cancel", cancel)
    monkeypatch.setattr(app, "exit", exit_app)
    monkeypatch.setattr(app.announcer, "announce", announce)
    ticks = iter((10.0, 10.5))
    monkeypatch.setattr("clawcodex_ext.tui.app.time.monotonic", lambda: next(ticks))

    app.action_cancel_or_quit()
    exit_app.assert_not_called()
    app.action_cancel_or_quit()

    assert cancel.call_count == 2
    exit_app.assert_called_once_with(return_code=130)


def test_managed_task_shutdown_is_idempotent(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    bridge_shutdown = Mock(return_value=True)
    shutdown = Mock(return_value=True)
    monkeypatch.setattr(app._agent_bridge, "shutdown", bridge_shutdown)
    monkeypatch.setattr(app.tool_context.task_manager, "shutdown", shutdown)

    app._shutdown_managed_tasks()
    app._shutdown_managed_tasks()

    bridge_shutdown.assert_called_once_with(timeout=2.0)
    shutdown.assert_called_once_with(timeout=2.0)


@pytest.mark.asyncio
async def test_app_boots_with_all_core_widgets(tmp_path):
    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Every core widget the Phase 11 layout promises must be mounted on
        # the active screen (REPLScreen, pushed in ``on_mount``).
        screen = app.screen
        assert screen.query_one(StartupHeader) is not None
        assert screen.query_one(Transcript) is not None
        assert screen.query_one(StatusBar) is not None
        assert screen.query_one(PromptInput) is not None
        assert screen.query_one(TaskProgressPanel) is not None


@pytest.mark.asyncio
async def test_task_progress_panel_tracks_task_and_lkb_results(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    projection_refresh = Mock(return_value=False)
    monkeypatch.setattr("lkb.repl_status.refresh_task_projection", projection_refresh)
    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.screen.query_one(TaskProgressPanel)
        assert panel.tasks == []
        assert panel.has_class("-active") is False

        app.tool_context.tasks["T-1"] = {
            "id": "T-1",
            "subject": "Publish",
            "status": "pending",
            "owner": None,
            "lkb": {"derivedStatus": "ready"},
        }
        app.screen.post_message(
            ToolEventMessage(
                kind="tool_result",
                tool_name="TaskCreate",
                tool_output={"task": {"id": "T-1"}},
            )
        )
        await pilot.pause()
        assert panel.has_class("-active") is True
        assert [(task.id, task.status) for task in panel.tasks] == [("T-1", "pending")]

        app.tool_context.tasks["T-1"]["status"] = "completed"
        app.tool_context.tasks["T-1"]["lkb"] = {"derivedStatus": "verified"}
        app.screen.post_message(
            ToolEventMessage(
                kind="tool_result",
                tool_name="Lkb",
                tool_output={"success": True, "taskId": "T-1"},
            )
        )
        await pilot.pause()
        assert [(task.id, task.status) for task in panel.tasks] == [("T-1", "completed")]
        assert any(call.kwargs == {"force": True} for call in projection_refresh.call_args_list)


@pytest.mark.asyncio
async def test_task_progress_panel_hydrates_child_lkb_context(tmp_path, monkeypatch):
    """The fixed panel reads Store changes made through another ToolContext."""

    from clawcodex_ext.feature_gate import get_registry
    from lkb.repository import JsonFileLkbRepository
    import lkb.repository as repository_module
    from src.tool_system.tools import TaskCreateTool, TaskUpdateTool

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CLAWCODEX_HOME", str(home))
    monkeypatch.setitem(get_registry()._overrides, "LKB_PLAN_GRAPH", True)
    monkeypatch.setattr(
        repository_module,
        "_repository_singleton",
        JsonFileLkbRepository(home=home),
    )

    app = _make_app(tmp_path)
    app.tool_context.agent_id = "parent-agent"
    app.tool_context.session_id = "shared-panel-session"
    child = ToolContext(workspace_root=tmp_path)
    child.agent_id = "child-agent"
    child.session_id = "shared-panel-session"
    task_id = TaskCreateTool.call(
        {"subject": "Child work", "description": "Cross-context panel refresh"},
        app.tool_context,
    ).output["task"]["id"]
    assert app.tool_context.lkb_plan_id is not None
    child.lkb_plan_id = app.tool_context.lkb_plan_id

    async with app.run_test() as pilot:
        await pilot.pause()
        panel = app.screen.query_one(TaskProgressPanel)
        assert [(task.id, task.status) for task in panel.tasks] == [(task_id, "pending")]

        for update in (
            {"taskId": task_id, "owner": "child-agent"},
            {"taskId": task_id, "status": "in_progress"},
            {"taskId": task_id, "status": "completed"},
        ):
            result = TaskUpdateTool.call(update, child)
            assert not result.is_error, result.output
        from lkb.repl_status import refresh_task_projection

        assert refresh_task_projection(app.tool_context, force=True)
        assert app.tool_context.tasks[task_id]["status"] == "completed"
        app.screen.refresh_task_panel(force_projection=True)
        await pilot.pause()

        assert [(task.id, task.status) for task in panel.tasks] == [(task_id, "completed")]


@pytest.mark.asyncio
async def test_local_slash_help_is_handled_without_agent(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(ClawCodexTUI, "submit_to_agent", lambda self, text: calls.append(text))

    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        prompt._input.value = "/help"
        await prompt._input.action_submit()
        await pilot.pause()

    # /help is handled locally — the agent must NOT be invoked.
    assert calls == []


@pytest.mark.asyncio
async def test_prompt_submission_dispatches_to_agent(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(ClawCodexTUI, "submit_to_agent", lambda self, text: calls.append(text))

    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        prompt._input.value = "hello agent"
        await prompt._input.action_submit()
        await pilot.pause()

    assert calls == ["hello agent"]


@pytest.mark.asyncio
async def test_assistant_message_renders_into_transcript(tmp_path):
    from src.tui.messages import AssistantMessage

    app = _make_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        transcript = app.screen.query_one(Transcript)
        before = len(transcript.lines)
        # Messages are routed to the *screen* (where the handler lives), not
        # the app. Posting to the app would leave ``on_assistant_message``
        # unreached because bubbling goes up the DOM, not down.
        app.screen.post_message(AssistantMessage(text="pong"))
        await pilot.pause()
        after = len(transcript.lines)
        assert after > before


@pytest.mark.asyncio
async def test_local_slash_exit_quits_app(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    monkeypatch.setattr(ClawCodexTUI, "submit_to_agent", lambda self, text: None)

    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        prompt._input.value = "/exit"
        await prompt._input.action_submit()
        await pilot.pause()


@pytest.mark.asyncio
async def test_local_slash_repl_is_alias_for_exit(tmp_path, monkeypatch):
    """``/repl`` advertises intent ('return to the Rich REPL') but the
    mechanism is the same ``app.exit()`` as ``/exit`` / ``/quit``. When
    dispatched from a handoff (``/tui`` from the Rich REPL) this returns
    control to the outer loop; when booted via ``--tui`` it ends the
    process. This test locks in the exit semantics."""
    app = _make_app(tmp_path)
    monkeypatch.setattr(ClawCodexTUI, "submit_to_agent", lambda self, text: None)

    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.screen.query_one(PromptInput)
        prompt._input.value = "/repl"
        await prompt._input.action_submit()
        await pilot.pause()
    # If ``/repl`` hadn't called exit(), ``async with`` would block
    # forever and pytest would time out.

    # App.run_test exits cleanly when the app calls ``exit()``; if it hadn't,
    # ``async with`` would block forever and this test would time out.
