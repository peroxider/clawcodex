"""Stage 3f: /btw side-question command registration and basic invocation.

F-122-J stability-gate coverage.
"""

from __future__ import annotations

import pytest


class TestBtwCommandRegistration:
    """Verify /btw command is registered and callable."""

    def test_btw_command_in_builtin_list(self):
        from clawcodex_ext.command_system.builtins import get_builtin_commands

        cmds = get_builtin_commands()
        names = [c.name for c in cmds]
        assert "btw" in names, f"/btw not found in builtin commands: {names}"

    def test_btw_command_is_interactive(self):
        from clawcodex_ext.command_system.builtins import get_builtin_commands
        from clawcodex_ext.command_system.types import CommandType

        cmds = get_builtin_commands()
        btw = next((c for c in cmds if c.name == "btw"), None)
        assert btw is not None
        assert btw.command_type == CommandType.INTERACTIVE

    def test_btw_command_description(self):
        from clawcodex_ext.command_system.builtins import get_builtin_commands

        cmds = get_builtin_commands()
        btw = next((c for c in cmds if c.name == "btw"), None)
        assert btw is not None
        assert "侧边" in btw.description or "side" in btw.description.lower()

    def test_btw_command_safe_for_remote(self):
        from clawcodex_ext.command_system.safe_commands import REMOTE_SAFE_COMMANDS

        assert "btw" in REMOTE_SAFE_COMMANDS


class TestBtwCommandInvocation:
    """Verify /btw command execution paths."""

    def test_btw_empty_args_returns_usage(self):
        import asyncio
        from clawcodex_ext.command_system.btw_command import btw_command_run
        from clawcodex_ext.command_system.types import CommandContext

        ctx = CommandContext(workspace_root="/tmp", cwd="/tmp")
        outcome = asyncio.run(btw_command_run("", ctx))
        assert outcome.message is not None
        assert "Usage" in outcome.message
        assert outcome.display == "user"

    def test_btw_no_tool_context_returns_error(self):
        import asyncio
        from clawcodex_ext.command_system.btw_command import btw_command_run
        from clawcodex_ext.command_system.types import CommandContext

        ctx = CommandContext(workspace_root="/tmp", cwd="/tmp")
        outcome = asyncio.run(btw_command_run("what is this", ctx))
        # No tool_context → fallback rebuild fails → returns warning
        assert outcome.message is not None
        assert "⚠️" in outcome.message or "无法" in outcome.message


class TestSideQuestionModuleImports:
    """Verify side-question submodules import cleanly."""

    def test_forked_agent_import(self):
        from clawcodex_ext.agent.forked_agent import (
            CacheSafeParams,
            ForkedAgentParams,
            ForkedAgentResult,
            get_last_cache_safe_params,
            run_forked_agent,
            save_cache_safe_params,
        )

        assert callable(run_forked_agent)
        assert callable(save_cache_safe_params)
        assert callable(get_last_cache_safe_params)

    def test_side_question_import(self):
        from clawcodex_ext.agent.side_question import (
            SideQuestionResult,
            extract_side_question_response,
            run_side_question,
        )

        assert callable(run_side_question)
        assert callable(extract_side_question_response)

    def test_cache_safe_params_roundtrip(self):
        from clawcodex_ext.agent.forked_agent import (
            CacheSafeParams,
            get_last_cache_safe_params,
            save_cache_safe_params,
        )
        from clawcodex_ext.tool_system.context import ToolContext

        ctx = ToolContext(workspace_root="/tmp")
        params = CacheSafeParams(
            system_prompt="test prompt",
            tool_use_context=ctx,
            user_context={"claudeMd": "test"},
        )
        save_cache_safe_params(params)
        retrieved = get_last_cache_safe_params()
        assert retrieved is not None
        assert retrieved.system_prompt == "test prompt"


class TestExtractSideQuestionResponse:
    """Verify response extraction from fork message stream."""

    def test_extract_from_text_content(self):
        from clawcodex_ext.agent.side_question import extract_side_question_response
        from clawcodex_ext.types.messages import AssistantMessage

        msg = AssistantMessage(content="  Hello world  ")
        result = extract_side_question_response([msg])
        assert result == "Hello world"

    def test_extract_from_text_blocks(self):
        from clawcodex_ext.agent.side_question import extract_side_question_response
        from clawcodex_ext.types.messages import AssistantMessage
        from clawcodex_ext.types.content_blocks import TextBlock

        msg = AssistantMessage(content=[TextBlock(text="Answer")])
        result = extract_side_question_response([msg])
        assert result == "Answer"

    def test_extract_empty_returns_none(self):
        from clawcodex_ext.agent.side_question import extract_side_question_response
        from clawcodex_ext.types.messages import AssistantMessage

        msg = AssistantMessage(content="")
        result = extract_side_question_response([msg])
        assert result is None

    def test_extract_no_assistant_returns_none(self):
        from clawcodex_ext.agent.side_question import extract_side_question_response
        from clawcodex_ext.types.messages import UserMessage

        result = extract_side_question_response([UserMessage(content="hi")])
        assert result is None
