"""Spec-3 tests for the upstream-compatible `/goal` slash command."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawcodex_ext.command_system.engine import CommandEngine
from clawcodex_ext.command_system.registry import CommandRegistry
from clawcodex_ext.command_system.types import CommandContext, NullUIHost, UIOption
from clawcodex_ext.feature_gate import get_registry, reset_registry
from clawcodex_ext.goal.command import GOAL_COMMAND
from clawcodex_ext.goal.model import ThreadGoalStatus
from clawcodex_ext.goal.protocol import GoalEventLog, ThreadGoalProtocol
from clawcodex_ext.goal.files import MAX_THREAD_GOAL_OBJECTIVE_CHARS
from clawcodex_ext.goal.files import objective_text_for_edit
from clawcodex_ext.goal.service import GoalService
from clawcodex_ext.goal.store import GoalStore, goals_db_filename
from src.command_system.safe_commands import is_bridge_safe_command
from src.tui.state import AppState


def _run(coro):
    return asyncio.run(coro)


class ScriptedUIHost(NullUIHost):
    def __init__(
        self,
        *,
        selects: list[str | None] | None = None,
        prompts: list[str | None] | None = None,
    ) -> None:
        self.selects = list(selects or [])
        self.prompts = list(prompts or [])
        self.seen_selects: list[tuple[str, list[UIOption]]] = []
        self.seen_prompts: list[tuple[str, str]] = []

    async def select(
        self,
        title: str,
        options: list[UIOption],
        *,
        current: str | None = None,
    ) -> str | None:
        del current
        self.seen_selects.append((title, list(options)))
        return self.selects.pop(0) if self.selects else None

    async def prompt_text(
        self,
        title: str,
        *,
        default: str = "",
        placeholder: str | None = None,
    ) -> str | None:
        del placeholder
        self.seen_prompts.append((title, default))
        return self.prompts.pop(0) if self.prompts else None


def _context(tmp_path: Path, ui: ScriptedUIHost | None = None) -> CommandContext:
    service = GoalService(
        store=GoalStore(tmp_path / goals_db_filename()),
        codex_home=tmp_path / "codex-home",
    )
    events = GoalEventLog()
    api = ThreadGoalProtocol(service=service, events=events)
    context = CommandContext(
        workspace_root=Path("/tmp"),
        cwd=Path("/tmp"),
        tool_context=SimpleNamespace(session_id="spec-1"),
        ui=ui or NullUIHost(),
    )
    context.goal_service = service  # type: ignore[attr-defined]
    context.goal_api = api  # type: ignore[attr-defined]
    context.goal_events = events  # type: ignore[attr-defined]
    return context


@pytest.fixture(autouse=True)
def _fresh_feature_registry():
    reg = reset_registry()
    yield reg
    reset_registry()


def test_goal_command_is_feature_gated_by_goals_flag():
    reg = get_registry()

    assert GOAL_COMMAND.is_enabled() is True
    assert reg.get_flag("goals") is not None

    reg.set_override("goals", False)

    assert GOAL_COMMAND.is_enabled() is False


def test_goal_command_remains_interactive_not_bridge_safe():
    assert is_bridge_safe_command(GOAL_COMMAND) is False


def test_goal_command_user_visible_arguments_only_include_upstream_set():
    assert GOAL_COMMAND.argument_hint == "[<objective>|clear|edit|pause|resume]"


def test_bare_goal_shows_usage_when_no_goal_is_set(tmp_path: Path):
    outcome = _run(GOAL_COMMAND.run("", _context(tmp_path)))

    assert outcome.display == "system"
    assert outcome.should_query is False
    assert "/goal [<objective>|clear|edit|pause|resume]" in outcome.message
    assert "No goal is currently set." in outcome.message


def test_goal_objective_creates_active_goal(tmp_path: Path):
    context = _context(tmp_path)

    outcome = _run(GOAL_COMMAND.run("ship spec 3", context))

    assert outcome.display == "system"
    assert outcome.should_query is True
    assert "Goal active" in outcome.message
    assert context.goal_service.get_goal("spec-1").objective == "ship spec 3"  # type: ignore[attr-defined]


def test_goal_command_uses_tool_context_goal_service_for_runtime_continuation(
    tmp_path: Path,
):
    from clawcodex_ext.goal.runtime import (
        CONTINUATION_STEERING_MARKER,
        goal_runtime_for_context,
    )

    service = GoalService(
        store=GoalStore(tmp_path / goals_db_filename()),
        codex_home=tmp_path / "codex-home",
    )
    tool_context = SimpleNamespace(
        session_id="spec-1",
        goal_service=service,
    )
    context = CommandContext(
        workspace_root=Path("/tmp"),
        cwd=Path("/tmp"),
        tool_context=tool_context,
        ui=NullUIHost(),
    )

    _run(GOAL_COMMAND.run("continue after slash command", context))

    runtime = goal_runtime_for_context(tool_context)
    request = runtime.continue_if_idle() if runtime is not None else None

    assert service.get_goal("spec-1").objective == "continue after slash command"
    assert request is not None
    assert CONTINUATION_STEERING_MARKER in str(request.messages[0].content)


def test_goal_objective_materializes_long_input(tmp_path: Path):
    context = _context(tmp_path)
    objective = "long goal\n" + ("x" * MAX_THREAD_GOAL_OBJECTIVE_CHARS)

    outcome = _run(GOAL_COMMAND.run(objective, context))

    goal = context.goal_service.get_goal("spec-1")  # type: ignore[attr-defined]
    assert "Goal active" in outcome.message
    assert goal.objective.startswith("Read the Codex goal objective file at ")
    assert objective_text_for_edit(
        goal.objective,
        codex_home=tmp_path / "codex-home",
    ) == objective


def test_goal_objective_requires_confirmation_before_replacing_unfinished_goal(
    tmp_path: Path,
):
    ui = ScriptedUIHost(selects=["cancel"])
    context = _context(tmp_path, ui)
    context.goal_service.set_goal("spec-1", "current")  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("replacement", context))

    assert outcome.display == "skip"
    assert "Replace goal?" in ui.seen_selects[0][0]
    assert context.goal_service.get_goal("spec-1").objective == "current"  # type: ignore[attr-defined]


def test_goal_objective_confirmed_replace_clears_then_sets_new_goal(tmp_path: Path):
    ui = ScriptedUIHost(selects=["replace"])
    context = _context(tmp_path, ui)
    old = context.goal_service.set_goal("spec-1", "current")  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("replacement", context))
    current = context.goal_service.get_goal("spec-1")  # type: ignore[attr-defined]

    assert "Goal active" in outcome.message
    assert current.objective == "replacement"
    assert current.goal_id != old.goal_id
    assert [message.method for message in context.goal_events.messages] == [  # type: ignore[attr-defined]
        "thread/goal/get",
        "thread/goal/clear",
        "thread/goal/cleared",
        "thread/goal/set",
        "thread/goal/updated",
    ]


def test_goal_objective_replaces_complete_goal_without_confirmation(tmp_path: Path):
    ui = ScriptedUIHost()
    context = _context(tmp_path, ui)
    old = context.goal_service.set_goal("spec-1", "complete me")  # type: ignore[attr-defined]
    context.goal_service.update_goal(  # type: ignore[attr-defined]
        "spec-1",
        ThreadGoalStatus.COMPLETE,
        expected_goal_id=old.goal_id,
    )

    outcome = _run(GOAL_COMMAND.run("fresh", context))

    assert "Goal active" in outcome.message
    assert ui.seen_selects == []
    assert context.goal_service.get_goal("spec-1").objective == "fresh"  # type: ignore[attr-defined]


def test_goal_clear_deletes_current_goal(tmp_path: Path):
    context = _context(tmp_path)
    context.goal_service.set_goal("spec-1", "delete")  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("clear", context))

    assert outcome.message == "Goal cleared"
    assert context.goal_service.get_goal("spec-1") is None  # type: ignore[attr-defined]


def test_goal_pause_and_resume_update_status(tmp_path: Path):
    context = _context(tmp_path)
    context.goal_service.set_goal("spec-1", "toggle")  # type: ignore[attr-defined]

    paused = _run(GOAL_COMMAND.run("pause", context))
    resumed = _run(GOAL_COMMAND.run("resume", context))

    assert "Goal paused" in paused.message
    assert "Goal active" in resumed.message
    assert context.goal_service.get_goal("spec-1").status is ThreadGoalStatus.ACTIVE  # type: ignore[attr-defined]


def test_goal_command_updates_app_state_goal_status(tmp_path: Path):
    context = _context(tmp_path)
    context.app_state = AppState(model="test", provider="test")  # type: ignore[attr-defined]

    _run(GOAL_COMMAND.run("sync status", context))
    _run(GOAL_COMMAND.run("pause", context))

    assert context.app_state.goal_status["status"] == "paused"  # type: ignore[attr-defined]
    assert context.app_state.goal_status["objective"] == "sync status"  # type: ignore[attr-defined]

    _run(GOAL_COMMAND.run("clear", context))

    assert context.app_state.goal_status is None  # type: ignore[attr-defined]


def test_bare_goal_summary_updates_app_state_goal_status(tmp_path: Path):
    context = _context(tmp_path)
    context.app_state = AppState(model="test", provider="test")  # type: ignore[attr-defined]
    context.goal_service.set_goal("spec-1", "sync on summary")  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("", context))

    assert "Objective: sync on summary" in outcome.message
    assert context.app_state.goal_status["status"] == "active"  # type: ignore[attr-defined]
    assert context.app_state.goal_status["objective"] == "sync on summary"  # type: ignore[attr-defined]


def test_goal_edit_prompts_and_preserves_paused_status(tmp_path: Path):
    ui = ScriptedUIHost(prompts=["edited objective"])
    context = _context(tmp_path, ui)
    context.goal_service.set_goal("spec-1", "current")  # type: ignore[attr-defined]
    context.goal_service.pause_goal("spec-1")  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("edit", context))

    goal = context.goal_service.get_goal("spec-1")  # type: ignore[attr-defined]
    assert "Goal paused" in outcome.message
    assert goal.objective == "edited objective"
    assert goal.status is ThreadGoalStatus.PAUSED


@pytest.mark.parametrize(
    "terminal_status",
    [ThreadGoalStatus.BUDGET_LIMITED, ThreadGoalStatus.COMPLETE],
)
def test_goal_edit_reactivates_terminal_goal_and_resets_usage(
    tmp_path: Path,
    terminal_status: ThreadGoalStatus,
):
    ui = ScriptedUIHost(prompts=["edited terminal objective"])
    context = _context(tmp_path, ui)
    goal = context.goal_service.set_goal(  # type: ignore[attr-defined]
        "spec-1",
        "terminal",
        token_budget=10,
    )
    context.goal_service.account_usage(  # type: ignore[attr-defined]
        "spec-1",
        expected_goal_id=goal.goal_id,
        token_delta=10,
        elapsed_seconds=5,
    )
    if terminal_status is ThreadGoalStatus.COMPLETE:
        limited = context.goal_service.get_goal("spec-1")  # type: ignore[attr-defined]
        context.goal_service.update_goal(  # type: ignore[attr-defined]
            "spec-1",
            ThreadGoalStatus.COMPLETE,
            expected_goal_id=limited.goal_id,
        )

    outcome = _run(GOAL_COMMAND.run("edit", context))

    edited = context.goal_service.get_goal("spec-1")  # type: ignore[attr-defined]
    assert "Goal active" in outcome.message
    assert edited.objective == "edited terminal objective"
    assert edited.status is ThreadGoalStatus.ACTIVE
    assert edited.token_budget == 10
    assert edited.tokens_used == 0
    assert edited.time_used_seconds == 0
    assert edited.goal_id != goal.goal_id


def test_goal_edit_reads_materialized_objective_for_default_text(tmp_path: Path):
    ui = ScriptedUIHost(prompts=["edited long objective"])
    context = _context(tmp_path, ui)
    objective = "editable goal\n" + ("x" * MAX_THREAD_GOAL_OBJECTIVE_CHARS)
    context.goal_service.set_goal("spec-1", objective)  # type: ignore[attr-defined]

    outcome = _run(GOAL_COMMAND.run("edit", context))

    assert "Goal active" in outcome.message
    assert ui.seen_prompts == [("Edit goal", objective)]


def test_bare_goal_summary_omits_resume_for_budget_limited_goal(tmp_path: Path):
    context = _context(tmp_path)
    goal = context.goal_service.set_goal("spec-1", "budget", token_budget=1)  # type: ignore[attr-defined]
    context.goal_service.account_usage(  # type: ignore[attr-defined]
        "spec-1",
        expected_goal_id=goal.goal_id,
        token_delta=1,
        elapsed_seconds=1,
    )

    outcome = _run(GOAL_COMMAND.run("", context))

    assert "Status: limited by budget" in outcome.message
    assert "Commands: /goal edit, /goal clear" in outcome.message
    assert "resume" not in outcome.message.split("Commands:", 1)[1]


@pytest.mark.parametrize("legacy_args", ["status", "continue", "complete"])
def test_legacy_goal_words_are_treated_as_objectives(tmp_path: Path, legacy_args: str):
    context = _context(tmp_path)

    outcome = _run(GOAL_COMMAND.run(legacy_args, context))

    assert outcome.display == "system"
    assert outcome.should_query is True
    assert "Goal active" in outcome.message
    assert context.goal_service.get_goal("spec-1").objective == legacy_args  # type: ignore[attr-defined]
    assert "Current goal status" not in outcome.message
    assert "Goal counter reset" not in outcome.message
    assert "Goal marked complete" not in outcome.message


def test_engine_reports_goal_disabled_when_gate_is_off():
    registry = CommandRegistry()
    registry.register(GOAL_COMMAND)
    engine = CommandEngine(
        registry=registry,
        workspace_root=Path("/tmp"),
        context=_context(tmp_path=Path("/tmp")),
    )
    get_registry().set_override("goals", False)

    result = _run(engine.execute("/goal"))

    assert result.success is False
    assert "disabled" in result.error.lower()
