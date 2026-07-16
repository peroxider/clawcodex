"""Tests for TUI slash command dispatch.

Covers all commands in ``LOCAL_BUILTINS`` to ensure they are properly
dispatched by ``dispatch_local_command`` without crashing, and that
registry-backed commands go through ``dispatch_registry_command``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from src.tui.commands import (
    LOCAL_BUILTINS,
    CommandDispatchResult,
    build_command_suggestions,
    build_command_words,
    dispatch_local_command,
    dispatch_registry_command,
)
from src.tool_system.registry import ToolRegistry
from src.tool_system.context import ToolContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def tool_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock()
    session.conversation = MagicMock()
    session.conversation.messages = []
    return session


# ---------------------------------------------------------------------------
# LOCAL_BUILTINS completeness
# ---------------------------------------------------------------------------

_KNOWN_HANDLED_COMMANDS: set[str] = {
    # Handled by dispatch_local_command
    "/help",
    "/exit",
    "/quit",
    "/q",
    "/repl",
    "/clear",
    "/tools",
    "/stream",
    "/model",
    "/models",
    "/effort",
    "/history",
    "/cost",
    "/idle",
    "/theme",
    "/diff",
    "/mcp",
    "/tasks",
    "/rewind",
    "/resume",
    "/permission",
    "/forecast",
    # Handled by dispatch_registry_command (NOT by dispatch_local_command)
    "/init",
    "/provider",
    "/lkb",
    "/recap",
    "/btw",
    "/advisor",
    "/buddy",
    "/compact",
    "/context",
    "/cron-list",
    "/cron-delete",
    "/cron-run",
    "/cron-runs",
    "/cron-status",
    "/goal",
    "/export",
    "/output-style",
    "/security-review",
    "/statusline",
    "/telemetry",
    "/copy",
    "/doctor",
    "/logo",
    "/memory",
    "/permissions",
    "/release-notes",
    "/rename",
    "/stickers",
    "/vim",
    "/voice",
    "/workflows",
    "/deep-research",
    "/render-last",
    "/skills",
    "/tts",
    "/ultraplan",
}


def test_all_local_builtins_have_handlers():
    """Every command in ``LOCAL_BUILTINS`` must have a known handler."""
    for cmd in LOCAL_BUILTINS:
        assert cmd in _KNOWN_HANDLED_COMMANDS, (
            f"{cmd} is in LOCAL_BUILTINS but not in _KNOWN_HANDLED_COMMANDS"
        )


def test_all_suggestion_commands_have_handlers(tmp_path: Path):
    """Every command returned by ``build_command_suggestions`` must have
    a known handler (local, registry, or skill)."""
    suggestions = build_command_suggestions(tmp_path)
    for s in suggestions:
        # Skills are handled by the skill system
        if s.source == "skills":
            continue
        slash = f"/{s.name}"
        assert slash in _KNOWN_HANDLED_COMMANDS, (
            f"{slash} (source={s.source}) is in suggestions but has no known handler"
        )


@pytest.mark.asyncio
async def test_registry_fork_result_is_returned_as_assistant_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clawcodex_ext.command_system.engine import CommandResult

    async def _execute_command_async(name, args, context):
        del args, context
        return CommandResult.success_assistant(name, "VERDICT: PASS")

    monkeypatch.setattr(
        "src.command_system.builtins.execute_command_async",
        _execute_command_async,
    )

    result = await dispatch_registry_command("/verify", command_context=MagicMock())

    assert result.handled is True
    assert result.assistant_text == "VERDICT: PASS"
    assert result.assistant_name == "verify"
    assert result.prompt_text is None


# ---------------------------------------------------------------------------
# dispatch_local_command — each LOCAL_BUILTINS command
# ---------------------------------------------------------------------------


def test_dispatch_help(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/help", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert "Slash commands" in (result.system_text or "")


def test_dispatch_exit(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/exit", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__exit__"


def test_dispatch_quit(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/quit", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__exit__"


def test_dispatch_q(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/q", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__exit__"


def test_dispatch_repl(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/repl", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__repl__"


def test_dispatch_clear(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/clear", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__clear__"


def test_dispatch_tools(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/tools", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    # Should contain registered tool names (initially empty)
    assert "tools" in (result.system_text or "").lower()


def test_dispatch_stream_on(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/stream on", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__stream_on__"


def test_dispatch_stream_off(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/stream off", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__stream_off__"


def test_dispatch_stream_toggle(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/stream toggle", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__stream_toggle__"


def test_dispatch_stream_no_arg_shows_status(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/stream", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.system_text == "__stream_status__"


def test_dispatch_model(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/model", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "model"


def test_dispatch_models(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/models", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "model"


def test_dispatch_effort(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/effort", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "effort"


def test_dispatch_history(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/history", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "history"


def test_dispatch_cost(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/cost", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "cost"


def test_dispatch_idle(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/idle", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "idle"


def test_dispatch_theme(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/theme", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "theme"


def test_dispatch_diff(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/diff", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "diff"


def test_dispatch_mcp(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/mcp", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "mcp"


def test_dispatch_tasks(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/tasks", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "tasks"


def test_dispatch_rewind(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/rewind", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "rewind"


def test_dispatch_resume(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/resume", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "resume"


def test_dispatch_permission(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/permission", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "permission"


def test_dispatch_forecast_dialog(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/forecast", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "forecast"


def test_dispatch_forecast_run_dialog(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/forecast run", session=mock_session, workspace_root=tmp_path, tool_registry=tool_registry
    )
    assert result.handled is True
    assert result.open_dialog == "forecast"


def test_dispatch_forecast_status_falls_through(mock_session, tmp_path, tool_registry):
    result = dispatch_local_command(
        "/forecast status",
        session=mock_session,
        workspace_root=tmp_path,
        tool_registry=tool_registry,
    )
    assert result.handled is False


# ---------------------------------------------------------------------------
# Unknown command falls through
# ---------------------------------------------------------------------------


def test_dispatch_unknown_returns_not_handled(mock_session, tmp_path, tool_registry):
    """An unknown slash command must return ``handled=False``."""
    result = dispatch_local_command(
        "/bogus-command-xyz",
        session=mock_session,
        workspace_root=tmp_path,
        tool_registry=tool_registry,
    )
    assert result.handled is False


# ---------------------------------------------------------------------------
# build_command_words consistency
# ---------------------------------------------------------------------------


def test_build_command_words_includes_local_builtins(tmp_path: Path):
    """Every item in ``LOCAL_BUILTINS`` must appear in ``build_command_words``."""
    words = build_command_words(tmp_path)
    word_set = {w.lower() for w in words}
    for cmd in LOCAL_BUILTINS:
        assert cmd.lower() in word_set, (
            f"{cmd} is in LOCAL_BUILTINS but missing from build_command_words"
        )


def test_build_command_suggestions_includes_local_builtins(tmp_path: Path):
    """Every item in ``LOCAL_BUILTINS`` must appear in ``build_command_suggestions``."""
    suggestions = build_command_suggestions(tmp_path)
    sugg_names = {f"/{s.name}".lower() for s in suggestions}
    for cmd in LOCAL_BUILTINS:
        assert cmd.lower() in sugg_names, (
            f"{cmd} is in LOCAL_BUILTINS but missing from build_command_suggestions"
        )
