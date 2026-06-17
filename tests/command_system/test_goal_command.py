"""Unit tests for :class:`clawcodex_ext.goal.command.GoalCommand`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import pytest

from clawcodex_ext.command_system.types import (
    InteractiveOutcome,
    NullUIHost,
    UIOption,
)
from clawcodex_ext.command_system.engine import CommandEngine
from clawcodex_ext.command_system.registry import CommandRegistry
from src.command_system.safe_commands import is_bridge_safe_command
from clawcodex_ext.goal import (
    MAX_OBJECTIVE_CHARS,
    GoalStatus,
    get_goal_registry,
    reset_goal_registry_for_tests,
)
from clawcodex_ext.goal.command import GOAL_COMMAND, GoalCommand


# ---------------------------------------------------------------------------
# Fake UIHost for tests
# ---------------------------------------------------------------------------


class _FakeUIHost:
    """Programmable stand-in for :class:`UIHost`.

    Tests populate ``select_responses`` with the value to return for
    each ``select`` call. ``displayed`` collects every ``display``
    call so tests can assert on the dialog preview text.
    """

    def __init__(
        self,
        select_responses: Optional[list[Optional[str]]] = None,
        prompt_responses: Optional[list[Optional[str]]] = None,
    ) -> None:
        self.select_responses = list(select_responses or [])
        self.prompt_responses = list(prompt_responses or [])
        self.displayed: list[tuple[str, str]] = []
        self._select_index = 0
        self._prompt_index = 0

    async def select(
        self, title: str, options, *, current: Optional[str] = None
    ) -> Optional[str]:
        if self._select_index >= len(self.select_responses):
            return None
        value = self.select_responses[self._select_index]
        self._select_index += 1
        return value

    async def prompt_text(self, title: str, **_: object) -> Optional[str]:
        if self._prompt_index >= len(self.prompt_responses):
            return None
        value = self.prompt_responses[self._prompt_index]
        self._prompt_index += 1
        return value

    async def display(self, title: str, body: str) -> None:
        self.displayed.append((title, body))


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _make_context(session_id: str = "test-session", ui=None):
    """Build a minimal ``CommandContext`` for testing.

    We avoid importing the full ``create_command_context`` factory
    because that requires ``HistoryLog`` / ``CostTracker`` setup. A
    duck-typed object with the attributes the command reads is
    sufficient.
    """
    from types import SimpleNamespace
    from clawcodex_ext.goal.controller import GoalController

    tool_ctx = SimpleNamespace(session_id=session_id)
    ctx = SimpleNamespace(
        workspace_root=Path("/tmp"),
        cwd=Path("/tmp"),
        config={},
        tool_context=tool_ctx,
        ui=ui or NullUIHost(),
    )
    return ctx


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_goal_registry_for_tests()
    yield
    reset_goal_registry_for_tests()


@pytest.fixture(autouse=True)
def _install_fake_storage(monkeypatch):
    """Replace SessionStorage so persist_goal writes to memory."""
    from clawcodex_ext.goal import storage as goal_storage

    class _FakeStorage:
        instances: dict = {}

        def __init__(self, session_id=None, **_: object) -> None:
            self.session_id = session_id or "fake"
            self.written = []
            type(self).instances[self.session_id] = self

        def write_raw(self, data):
            self.written.append(data)

        def flush(self):
            return None

        def read_transcript(self):
            return list(self.written)

    _FakeStorage.instances.clear()
    import src.services.session_storage as ss

    monkeypatch.setattr(ss, "SessionStorage", _FakeStorage)
    yield
    _FakeStorage.instances.clear()


# ---------------------------------------------------------------------------
# Subcommand parsing
# ---------------------------------------------------------------------------


def test_status_no_goal_message():
    ctx = _make_context()
    outcome = _run(GOAL_COMMAND.run("", ctx))
    assert outcome.display == "system"
    assert "No active goal" in outcome.message


def test_status_with_goal_shows_full_block():
    ctx = _make_context()
    # First set a goal.
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("status", ctx))
    assert "Status: active" in outcome.message
    assert "ship it" in outcome.message
    assert "Turns executed: 0" in outcome.message


def test_alias_status_works():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("STATUS", ctx))
    assert "Status: active" in outcome.message


def test_no_args_shows_status():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("", ctx))
    assert "Status: active" in outcome.message


# ---------------------------------------------------------------------------
# Setting a goal
# ---------------------------------------------------------------------------


def test_set_objective_returns_should_query():
    ctx = _make_context()
    outcome = _run(GOAL_COMMAND.run("ship it", ctx))
    assert outcome.should_query is True
    assert "Goal set" in outcome.message


def test_set_objective_persists_state():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    state = get_goal_registry().get("test-session")
    assert state is not None
    assert state.status == GoalStatus.ACTIVE
    assert state.objective == "ship it"


def test_set_objective_too_long_returns_message_no_set():
    ctx = _make_context()
    long_text = "x" * (MAX_OBJECTIVE_CHARS + 1)
    outcome = _run(GOAL_COMMAND.run(long_text, ctx))
    assert outcome.should_query is False
    assert str(MAX_OBJECTIVE_CHARS) in outcome.message
    # State was NOT set.
    assert get_goal_registry().get("test-session") is None


def test_set_objective_replace_confirm_replace():
    ui = _FakeUIHost(select_responses=["replace"])
    ctx = _make_context(ui=ui)
    _run(GOAL_COMMAND.run("first objective", ctx))
    outcome = _run(GOAL_COMMAND.run("second objective", ctx))
    state = get_goal_registry().get("test-session")
    assert state.objective == "second objective"
    assert "Goal set" in outcome.message
    # Display was called with the preview.
    assert any("first objective" in body for _, body in ui.displayed)


def test_set_objective_replace_confirm_keep():
    ui = _FakeUIHost(select_responses=["keep"])
    ctx = _make_context(ui=ui)
    _run(GOAL_COMMAND.run("first objective", ctx))
    outcome = _run(GOAL_COMMAND.run("second objective", ctx))
    state = get_goal_registry().get("test-session")
    assert state.objective == "first objective"
    assert "Keeping" in outcome.message


def test_set_objective_replace_confirm_cancel_is_skip():
    ui = _FakeUIHost(select_responses=[None])  # Esc / Cancel
    ctx = _make_context(ui=ui)
    _run(GOAL_COMMAND.run("first objective", ctx))
    outcome = _run(GOAL_COMMAND.run("second objective", ctx))
    state = get_goal_registry().get("test-session")
    assert state.objective == "first objective"
    assert outcome.display == "skip"


def test_set_objective_with_complete_existing_does_not_confirm():
    """A completed goal should not block replacement with a new one."""
    ui = _FakeUIHost(select_responses=[])
    ctx = _make_context(ui=ui)
    _run(GOAL_COMMAND.run("first objective", ctx))
    _run(GOAL_COMMAND.run("complete", ctx))
    # Now no confirm dialog should pop up.
    outcome = _run(GOAL_COMMAND.run("second objective", ctx))
    state = get_goal_registry().get("test-session")
    assert state.objective == "second objective"
    assert "Goal set" in outcome.message


def test_set_objective_in_null_ui_defaults_to_replace():
    """Headless surfaces default to replace (the user typed it explicitly)."""
    ctx = _make_context(ui=NullUIHost())
    _run(GOAL_COMMAND.run("first objective", ctx))
    outcome = _run(GOAL_COMMAND.run("second objective", ctx))
    state = get_goal_registry().get("test-session")
    assert state.objective == "second objective"
    assert "Goal set" in outcome.message


# ---------------------------------------------------------------------------
# Lifecycle subcommands
# ---------------------------------------------------------------------------


def test_clear_drops_state_and_writes_tombstone():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("clear", ctx))
    assert "cleared" in outcome.message.lower()
    assert get_goal_registry().get("test-session") is None


def test_clear_no_goal_is_noop():
    ctx = _make_context()
    outcome = _run(GOAL_COMMAND.run("clear", ctx))
    assert "nothing to clear" in outcome.message


def test_pause_and_resume_round_trip():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("pause", ctx))
    assert "paused" in outcome.message.lower()
    outcome = _run(GOAL_COMMAND.run("resume", ctx))
    assert "resumed" in outcome.message.lower()
    assert outcome.should_query is True


def test_resume_without_pause_is_message():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("resume", ctx))
    # Active goal cannot be resumed.
    assert "nothing to resume" in outcome.message or "active" in outcome.message.lower()


def test_continue_only_from_max_turns():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("continue", ctx))
    assert "max-turns" in outcome.message or "active" in outcome.message.lower()


def test_complete_marks_terminal():
    ctx = _make_context()
    _run(GOAL_COMMAND.run("ship it", ctx))
    outcome = _run(GOAL_COMMAND.run("complete", ctx))
    assert "complete" in outcome.message.lower()
    state = get_goal_registry().get("test-session")
    assert state.status == GoalStatus.COMPLETE


def test_no_active_session_returns_message():
    """Without a session_id the command degrades to a clean message."""
    ctx = _make_context(session_id="")
    outcome = _run(GOAL_COMMAND.run("ship it", ctx))
    assert "No active session" in outcome.message


def test_empty_objective_returns_usage_message():
    ctx = _make_context()
    outcome = _run(GOAL_COMMAND.run("   ", ctx))
    assert "Usage" in outcome.message


# ---------------------------------------------------------------------------
# Bridge safety
# ---------------------------------------------------------------------------


def test_goal_command_is_not_bridge_safe_by_type():
    """Per spec: ``/goal`` must NOT be bridgeSafe.

    ``is_bridge_safe_command`` blocks all InteractiveCommand by type
    (see ``safe_commands.py:48-53``).
    """
    assert is_bridge_safe_command(GOAL_COMMAND) is False


def test_goal_command_appears_in_registry():
    registry = CommandRegistry()
    registry.register(GOAL_COMMAND)
    assert registry.has("goal")
    # Alias registration.
    assert registry.get("g") is GOAL_COMMAND


# ---------------------------------------------------------------------------
# Engine dispatch
# ---------------------------------------------------------------------------


def test_engine_routes_goal_to_interactive_outcome():
    """Smoke test: the engine accepts ``/goal status`` and returns an
    InteractiveOutcome path result (not a crash)."""
    registry = CommandRegistry()
    registry.register(GOAL_COMMAND)
    engine = CommandEngine(registry=registry, workspace_root=Path("/tmp"))
    # Run via engine.execute — this exercises the async path.
    from clawcodex_ext.command_system.types import CommandContext

    ui = _FakeUIHost()
    ctx = CommandContext(
        workspace_root=Path("/tmp"),
        cwd=Path("/tmp"),
        tool_context=__import__("types").SimpleNamespace(session_id="engine-test"),
        ui=ui,
    )
    # Bind into the engine.
    engine.context = ctx
    outcome = _run(engine.execute("/goal status"))
    assert outcome.success is True
    assert "No active goal" in outcome.text
