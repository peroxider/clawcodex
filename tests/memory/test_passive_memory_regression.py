from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from clawcodex_ext.latent_memory.passive.config import PassiveMemoryConfig
from clawcodex_ext.latent_memory.passive.lifecycle import (
    PassiveMemoryRun,
    complete_top_level_run,
    flush_pending_writes,
)
from clawcodex_ext.latent_memory.passive.mcp_client import PassiveMemoryMcpClient
from clawcodex_ext.latent_memory.passive.message_utils import build_capture_messages
from clawcodex_ext.latent_memory.passive.scope import MemoryIds
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.query.engine import QueryEngine, QueryEngineConfig
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.defaults import build_default_registry
from clawcodex_ext.types.content_blocks import TextBlock
from clawcodex_ext.types.messages import AssistantMessage, UserMessage


def _run(coro):
    return asyncio.run(coro)


class _FakeMcpClient:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return SimpleNamespace(
            content=[{"type": "text", "text": json.dumps(self.result)}],
            structured_content=None,
        )


class TestPassiveMemoryRegressions(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.temp_dir.name)
        self.registry = build_default_registry()
        self.context = ToolContext(workspace_root=self.workspace)
        # 安装被动记忆插件（注册 on_query_start / on_query_end 钩子）
        from clawcodex_ext.latent_memory.plugin import install_passive_memory_plugin

        install_passive_memory_plugin()

    def tearDown(self) -> None:
        from clawcodex_ext.query.hook_registry import unregister_loop_hook

        unregister_loop_hook("passive_memory_recall", "on_query_start")
        unregister_loop_hook("passive_memory_capture", "on_query_end")
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    def _provider(self, finish_reason: str) -> MagicMock:
        provider = MagicMock()
        provider.chat_stream_response.side_effect = NotImplementedError()
        provider.chat.return_value = ChatResponse(
            content="Done.",
            model="test",
            usage={"input_tokens": 10, "output_tokens": 5},
            finish_reason=finish_reason,
            tool_uses=None,
        )
        return provider

    def _run_engine(self, finish_reason: str) -> MagicMock:
        marker = object()
        prepare = AsyncMock(return_value=("prompt with memory", marker))
        complete = MagicMock()
        engine = QueryEngine(
            QueryEngineConfig(
                cwd=self.workspace,
                provider=self._provider(finish_reason),
                tool_registry=self.registry,
                tools=self.registry.list_tools(),
                tool_context=self.context,
                system_prompt="base prompt",
            )
        )

        async def consume() -> None:
            async for _ in engine.submit_message("Implement it"):
                pass

        with (
            patch("clawcodex_ext.latent_memory.passive.prepare_top_level_run", prepare),
            patch("clawcodex_ext.latent_memory.passive.complete_top_level_run", complete),
        ):
            _run(consume())
        return complete

    def test_query_engine_accepts_openai_stop_as_completed(self) -> None:
        complete = self._run_engine("stop")

        complete.assert_called_once()
        self.assertEqual(complete.call_args.kwargs["terminal_reason"], "completed")

    def test_query_engine_rejects_max_tokens_as_completed(self) -> None:
        complete = self._run_engine("max_tokens")

        complete.assert_called_once()
        self.assertEqual(complete.call_args.kwargs["terminal_reason"], "incomplete")

    def test_background_writer_calls_add_messages(self) -> None:
        fake = _FakeMcpClient({"results": [{"event": "ADD", "id": "memory-1"}]})
        self.context.mcp_clients = {"latent-memory": fake}
        run = PassiveMemoryRun(
            config=PassiveMemoryConfig(enabled=True),
            ids=MemoryIds(
                user_id="ccx:chen:project:repo-12345678",
                agent_id="ccx:primary",
                run_id="ccxrun:session-123",
                project_key="repo-12345678",
            ),
            client=PassiveMemoryMcpClient(self.context, "latent-memory"),
            user_prompt="Remember this",
        )

        complete_top_level_run(
            run,
            [
                UserMessage(content="Remember this preference."),
                AssistantMessage(content=[TextBlock(text="Preference confirmed.")]),
            ],
            terminal_reason="completed",
        )

        self.assertTrue(flush_pending_writes(2.0))
        self.assertEqual(fake.calls[0][0], "memory_add_messages")

    def test_chinese_remember_prompt_is_strong_capture(self) -> None:
        _, strength = build_capture_messages(
            [
                UserMessage(
                    content="\u8bf7\u8bb0\u4f4f\uff1a\u4f18\u5148\u4f7f\u7528 PostgreSQL\u3002"
                ),
                AssistantMessage(content=[TextBlock(text="\u5df2\u786e\u8ba4\u3002")]),
            ],
            max_tokens=8000,
        )

        self.assertEqual(strength, "strong")
