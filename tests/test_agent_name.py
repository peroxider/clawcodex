"""F-89 — ``@agent-name`` 多入口统一支持测试。

Covers the three code paths that the F-89 rollout touched:

1. **Shared helpers** (``src.command_system.input_processing``) — the
   single source of truth that drives consistent behaviour across all
   five entry points (CLI, REPL, TUI, headless, orchestrator). These
   tests pin the *contract* so any drift in the helper automatically
   propagates to the entry-point tests.

2. **Headless error path** (``clawcodex_ext/entrypoints/headless.py``)
   — verifies that an unknown ``@agent-`` mention emits a friendly
   ``ResultEvent(is_error=True)`` instead of silently fowarding a
   typo'd instruction to the model. This is the regression test for
   the pre-fix behaviour where unknown agents fell through ``except
   Exception: pass``.

3. **Orchestrator prompt expansion**
   (``extensions/orchestrator/prompt_builder.py``) — verifies the
   orchestrator-side hook that expands ``@agent-`` mentions in
   generated prompts (mirrors the REPL/TUI behaviour) while leaving
   the rest of the prompt split intact.

REPL and TUI are already covered by their existing pipelines
(``clawcodex_ext/repl/core.py:_dispatch_user_input`` and
``clawcodex_ext/tui/screens/repl.py:on_prompt_submitted``); a passing
``format_unknown_agent_mention_error`` test plus the headless error
test is sufficient evidence that the helpers behave the same.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def agents_with_critic(tmp_path, monkeypatch):
    """Create an isolated CLAUDE_CONFIG_DIR + workspace with a custom
    ``critic`` agent loaded.
    """
    from clawcodex_ext.agent.agent_definitions import get_built_in_agents
    from src.agent.load_agents_dir import (
        clear_agent_definitions_cache,
        get_agent_definitions_with_overrides,
    )

    claude_home = tmp_path / "claude_home"
    claude_home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.setenv("CLAUDE_MANAGED_CONFIG_DIR", str(tmp_path / "managed"))

    agents_dir = claude_home / "agents"
    agents_dir.mkdir()
    (agents_dir / "critic.md").write_text(
        "---\nname: critic\ndescription: Reviews output for quality\n---\nYou review.\n",
        encoding="utf-8",
    )

    clear_agent_definitions_cache()
    try:
        agents = list(get_agent_definitions_with_overrides(str(tmp_path))) or list(
            get_built_in_agents()
        )
        yield tmp_path, agents
    finally:
        clear_agent_definitions_cache()


def test_unknown_agent_mention_isolated(agents_with_critic):
    """A bare ``@agent-foo`` in user text with no known agents returns
    the typo as unknown — used by REPL/TUI/headless to gate."""
    from src.command_system.input_processing import find_unknown_agent_mentions

    _workspace, agents = agents_with_critic
    unknown = find_unknown_agent_mentions("@agent-crtic review this", agents)
    assert unknown == ["crtic"]


def test_known_agent_mention_is_skipped(agents_with_critic):
    """A mention that resolves to a known agent must NOT appear in the
    unknown list (otherwise REPL would refuse the turn)."""
    from src.command_system.input_processing import find_unknown_agent_mentions

    _workspace, agents = agents_with_critic
    unknown = find_unknown_agent_mentions("@agent-critic review this", agents)
    assert unknown == []


def test_format_error_suggests_close_match(agents_with_critic):
    """The friendly error must suggest the close-match ``critic`` so
    users can recover from typos without consulting docs."""
    from src.command_system.input_processing import (
        format_unknown_agent_mention_error,
    )

    _workspace, agents = agents_with_critic
    msg = format_unknown_agent_mention_error(["crtic"], agents)
    assert "Unknown agent" in msg
    assert "crtic" in msg
    assert "critic" in msg  # close-match suggestion
    assert "@agent-" in msg


# ---------------------------------------------------------------------------
# Headless: unknown agent must short-circuit with a clear error
# ---------------------------------------------------------------------------


def _write_fake_agent_marker(workspace_root: Path, name: str) -> None:
    """Drop a minimal ``.claude/agents/<name>.md`` so the headless loader
    finds the agent alongside any built-ins."""
    agents_dir = workspace_root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: F-89 fixture agent\n---\nYou are {name}.\n",
        encoding="utf-8",
    )


def test_headless_unknown_agent_emits_error_result(tmp_path, monkeypatch):
    """When the prompt contains ``@agent-bogus``, run_headless should
    NOT call the LLM via ``chat()`` — it must emit a
    ``ResultEvent(is_error=True)`` with the friendly error text, and
    exit with a non-zero code (EX_CONFIG = 78).
    """
    from clawcodex_ext.providers.base import ChatResponse
    from src.agent.load_agents_dir import clear_agent_definitions_cache

    _write_fake_agent_marker(tmp_path, "critic")
    (tmp_path / "claude_home").mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude_home"))
    monkeypatch.setenv("CLAUDE_MANAGED_CONFIG_DIR", str(tmp_path / "managed"))
    clear_agent_definitions_cache()

    import clawcodex_ext.entrypoints.headless as ext_headless

    chat_calls = {"count": 0}

    class _TrackingProvider:
        def __init__(self, api_key, base_url=None, model=None, **_kwargs):
            pass

        def chat(self, messages, tools=None, **kwargs):
            chat_calls["count"] += 1
            return ChatResponse(
                content="should-not-be-called",
                model="fake-model",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
                tool_uses=None,
            )

        def chat_stream(self, messages, tools=None, **kwargs):
            raise NotImplementedError

    monkeypatch.setattr(
        ext_headless,
        "get_provider_class",
        lambda _name: lambda *a, **k: _TrackingProvider(*a, **k),
        raising=False,
    )
    monkeypatch.setattr(
        ext_headless,
        "get_provider_config",
        lambda _name: {
            "api_key": "test-key",
            "base_url": None,
            "default_model": "fake-model",
        },
        raising=False,
    )
    monkeypatch.setattr(ext_headless, "get_default_provider", lambda: "anthropic", raising=False)

    class _NoopRegistry:
        def list_tools(self):
            return []

    monkeypatch.setattr(
        ext_headless,
        "build_default_registry",
        lambda provider=None: _NoopRegistry(),
        raising=False,
    )

    from src.entrypoints import HeadlessOptions, run_headless

    stdout = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")
    stderr = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")

    try:
        code = run_headless(
            HeadlessOptions(
                prompt="please ask @agent-bogus to review",
                output_format="stream-json",
                input_format="text",
                stdout=stdout,
                stderr=stderr,
                workspace_root=tmp_path,
            )
        )
        stdout.seek(0)
        captured = stdout.read()
    finally:
        clear_agent_definitions_cache()

    assert chat_calls["count"] == 0, (
        f"LLM must not be called for unknown @agent-name (was called {chat_calls['count']} times)"
    )
    # EX_CONFIG (78) is the conventional exit code for config-level
    # mistakes (typo in agent name).
    assert code == 78
    # Parse stream-json to find the error ResultEvent.
    parsed_errors = []
    for line in captured.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("is_error") or obj.get("isError"):
            parsed_errors.append(obj)
    assert parsed_errors, f"no error ResultEvent in stream: {captured!r}"
    assert "Unknown agent" in str(parsed_errors[0])


def test_headless_known_agent_proceeds_to_provider(tmp_path, monkeypatch):
    """Sanity: a recognised ``@agent-critic`` mention does NOT block
    the turn — the provider gets called as usual. This pins the
    pre-existing behaviour so the unknown-agent fix doesn't regress
    known mentions.
    """
    from clawcodex_ext.providers.base import ChatResponse
    from clawcodex_ext.tool_system.renderers import AgentLoopResult
    from src.agent.load_agents_dir import clear_agent_definitions_cache

    _write_fake_agent_marker(tmp_path, "critic")
    (tmp_path / "claude_home").mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude_home"))
    monkeypatch.setenv("CLAUDE_MANAGED_CONFIG_DIR", str(tmp_path / "managed"))
    clear_agent_definitions_cache()

    import clawcodex_ext.entrypoints.headless as ext_headless

    provider_calls = {"count": 0}

    class _FakeProvider:
        def __init__(self, api_key, base_url=None, model=None, **_kwargs):
            pass

        def chat(self, messages, tools=None, **kwargs):
            provider_calls["count"] += 1
            return ChatResponse(
                content="reviewed",
                model="fake-model",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
                tool_uses=None,
            )

        def chat_stream(self, messages, tools=None, **kwargs):
            raise NotImplementedError

    monkeypatch.setattr(
        ext_headless,
        "get_provider_class",
        lambda _name: lambda *a, **k: _FakeProvider(*a, **k),
        raising=False,
    )
    monkeypatch.setattr(
        ext_headless,
        "get_provider_config",
        lambda _name: {
            "api_key": "test-key",
            "base_url": None,
            "default_model": "fake-model",
        },
        raising=False,
    )
    monkeypatch.setattr(ext_headless, "get_default_provider", lambda: "anthropic", raising=False)

    class _NoopRegistry:
        def list_tools(self):
            return []

    monkeypatch.setattr(
        ext_headless,
        "build_default_registry",
        lambda provider=None: _NoopRegistry(),
        raising=False,
    )

    from src.entrypoints import HeadlessOptions, run_headless

    stdout = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")
    stderr = tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")

    try:
        code = run_headless(
            HeadlessOptions(
                prompt="please ask @agent-critic to take a look",
                output_format="text",
                stdout=stdout,
                stderr=stderr,
                workspace_root=tmp_path,
            )
        )
        stdout.seek(0)
        captured = stdout.read()
    finally:
        clear_agent_definitions_cache()

    # The provider IS called (the unknown gate does not fire on known
    # mentions).
    assert provider_calls["count"] >= 1
    assert code == 0
    assert "reviewed" in captured


# ---------------------------------------------------------------------------
# Orchestrator: prompt expansion hooks for @agent- mentions
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_critic(tmp_path):
    """Create a workspace with a custom agent on disk so the orchestrator
    loader picks it up.
    """
    _write_fake_agent_marker(tmp_path, "critic")
    return tmp_path


def test_render_parts_expands_known_mention(workspace_with_critic):
    """Issue body containing ``@agent-critic`` produces a reminder
    block asking the model to delegate to the Agent tool — same shape
    as REPL/TUI emit.
    """
    from extensions.orchestrator.agent_runner import AgentSession
    from extensions.orchestrator.issue import Issue
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = Issue(
        id=1,
        identifier="F89-1",
        title="Try the critic",
        description="Please run @agent-critic on this plan.",
    )
    session = AgentSession.__new__(AgentSession)

    class _Ws:
        path = str(workspace_with_critic)

    session.workspace = _Ws()

    system_part, user_part = PromptBuilder.render_parts(issue, session=session)
    # The reminder is in the user half (matches REPL/TUI behaviour
    # where the attachment block is prepended to the prompt).
    combined = system_part + "\n\n" + user_part
    assert "<system-reminder>" in combined
    assert "@agent-critic" in combined
    assert 'subagent_type="critic"' in combined


def test_render_parts_strips_unknown_mention_with_warning(workspace_with_critic, caplog):
    """When the issue body mentions an unknown agent, the orchestrator
    strips it (so the model isn't misled by a non-existent reminder)
    and logs a warning. The renderer must NOT crash and must NOT block
    the agent run.
    """
    import logging

    from extensions.orchestrator.agent_runner import AgentSession
    from extensions.orchestrator.issue import Issue
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = Issue(
        id=2,
        identifier="F89-2",
        title="Bad mention",
        description="Talk to @agent-bogus about this.",
    )
    session = AgentSession.__new__(AgentSession)

    class _Ws:
        path = str(workspace_with_critic)

    session.workspace = _Ws()

    with caplog.at_level(logging.WARNING, logger="extensions.orchestrator.prompt_builder"):
        _system, user_part = PromptBuilder.render_parts(issue, session=session)

    assert "@agent-bogus" not in user_part
    assert any(
        "F-89" in record.message and "bogus" in record.message for record in caplog.records
    ), "renderer must log a warning for the stripped unknown agent"


def test_render_parts_no_session_still_succeeds(workspace_with_critic):
    """Best-effort: rendering without a session (e.g. dry-run / unit
    tests) must NOT raise. Falls back to no agent expansion.
    """
    from extensions.orchestrator.issue import Issue
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = Issue(
        id=3,
        identifier="F89-3",
        title="No session",
        description="Just rendering for a test.",
    )
    # session=None path
    system_part, user_part = PromptBuilder.render_parts(issue, session=None)
    assert user_part.strip()
    # System half may be empty (no marker in default template) — only
    # assert it doesn't crash and the user half is non-empty.
    assert system_part == "" or system_part.strip()


def test_render_parts_no_workspace_still_succeeds():
    """Even with ``session.workspace.path = None`` the helper returns
    the original prompt unchanged (best-effort) — guards against
    regressions where missing workspace metadata crashes the daemon.
    """
    from extensions.orchestrator.agent_runner import AgentSession
    from extensions.orchestrator.issue import Issue
    from extensions.orchestrator.prompt_builder import PromptBuilder

    issue = Issue(
        id=4,
        identifier="F89-4",
        title="No workspace",
        description="whatever",
    )
    session = AgentSession.__new__(AgentSession)

    class _Ws:
        path = None

    session.workspace = _Ws()

    _system, user_part = PromptBuilder.render_parts(issue, session=session)
    assert user_part.strip()
