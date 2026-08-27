from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from clawcodex_ext.latent_memory.passive.config import PassiveMemoryConfig
from clawcodex_ext.latent_memory.passive.lifecycle import (
    PassiveMemoryRun,
    _format_memories,
    _should_refresh_recall,
    complete_top_level_run,
    prepare_top_level_run,
)
from clawcodex_ext.latent_memory.passive.mcp_client import PassiveMemoryMcpClient
from clawcodex_ext.latent_memory.passive.message_utils import (
    build_capture_messages,
    build_search_query,
)
from clawcodex_ext.latent_memory.passive.scope import MemoryIds, build_memory_ids
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.query.agent_loop_compat import run_query_as_agent_loop
from clawcodex_ext.query.engine import QueryEngine, QueryEngineConfig
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.defaults import build_default_registry
from clawcodex_ext.types.content_blocks import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
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


class TestPassiveMemoryCore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    def test_ids_follow_stable_project_strategy(self) -> None:
        context = ToolContext(workspace_root=self.workspace)
        context.session_id = "session-123"
        config = PassiveMemoryConfig(enabled=True, human_id="Chen")
        remote = "git@github.com:example/clawcodex.git"
        expected_hash = hashlib.sha256(remote.encode()).hexdigest()[:8]

        with patch(
            "clawcodex_ext.latent_memory.passive.scope._git_value",
            side_effect=[str(self.workspace), remote],
        ):
            ids = build_memory_ids(config, context)

        self.assertEqual(
            ids.user_id,
            f"ccx:chen:project:{self.workspace.name.lower().strip('-._')}-{expected_hash}",
        )
        self.assertEqual(ids.agent_id, "ccx:primary")
        self.assertEqual(ids.run_id, "ccxrun:session-123")

    def test_recall_defaults_to_user_id_only_and_injects_memory(self) -> None:
        fake = _FakeMcpClient({"results": [{"id": "m1", "memory": "Prefer PostgreSQL."}]})
        context = ToolContext(workspace_root=self.workspace)
        context.session_id = "session-123"
        context.mcp_clients = {"latent-memory": fake}
        config = PassiveMemoryConfig(enabled=True, human_id="chen")

        system_prompt, run = _run(
            prepare_top_level_run(
                [UserMessage(content="Design the database layer")],
                "base prompt",
                context,
                config=config,
            )
        )

        self.assertIsNotNone(run)
        self.assertIn("Prefer PostgreSQL", system_prompt)
        _, arguments = fake.calls[0]
        self.assertIn("user_id", arguments)
        self.assertNotIn("agent_id", arguments)
        self.assertNotIn("run_id", arguments)

    def test_explicit_recall_query_ignores_wrapped_user_and_system_prompts(self) -> None:
        fake = _FakeMcpClient({"results": []})
        context = ToolContext(workspace_root=self.workspace)
        context.session_id = "bare-query-session"
        context.mcp_clients = {"latent-memory": fake}

        _run(
            prepare_top_level_run(
                [UserMessage(content="Please answer this benchmark question: Who adopted Momo?")],
                "SYSTEM TEXT THAT MUST NOT BE SEARCHED",
                context,
                config=PassiveMemoryConfig(enabled=True, human_id="chen"),
                recall_query="Who adopted Momo?",
            )
        )

        self.assertEqual(fake.calls[0][1]["query"], "Who adopted Momo?")

    def test_relevance_selection_is_presented_chronologically_with_historical_dates(self) -> None:
        results = [
            {
                "id": "new",
                "memory": "Newest relevant fact",
                "score": 0.99,
                "metadata": {"observed_at_unix": 1_704_067_200},
            },
            {
                "id": "old",
                "memory": "Oldest relevant fact",
                "score": 0.90,
                "metadata": {"observation_date": "2023-05-07"},
            },
            {
                "id": "unknown",
                "memory": "Unknown historical date",
                "score": 0.85,
                "created_at": "2022-01-01T00:00:00Z",
            },
        ]

        block = _format_memories(
            results,
            limit=3,
            max_chars=4000,
            present_chronologically=True,
            include_observation_dates=True,
            max_crystallized=3,
        )

        self.assertLess(block.index("old"), block.index("new"))
        self.assertLess(block.index("new"), block.index("unknown"))
        self.assertIn("(Sunday, May 07, 2023)", block)
        self.assertIn("(unknown date) Unknown historical date", block)
        self.assertNotIn("Saturday, January 01, 2022", block)

    def test_continuation_query_uses_one_previous_business_turn(self) -> None:
        messages = [
            UserMessage(content="Use JWT for authentication."),
            AssistantMessage(content=[TextBlock(text="JWT was selected.")]),
            UserMessage(content="继续按上次方案实现"),
        ]

        query = build_search_query(messages)

        self.assertIn("继续按上次方案实现", query)
        self.assertIn("Use JWT", query)
        self.assertNotIn("JWT was selected", query)

    def test_recall_filters_scores_crystals_and_preserves_xml_boundary(self) -> None:
        results = [
            {
                "id": "raw-1",
                "memory": "Top rule <unsafe>",
                "score": 0.80,
                "metadata": {"layer": "raw"},
            },
            {
                "id": "crystal-1",
                "memory": "Crystal rule",
                "score": 0.76,
                "metadata": {"layer": "crystallized", "source_memory_ids": ["s1"]},
            },
            {
                "id": "crystal-2",
                "memory": "Second crystal",
                "score": 0.75,
                "metadata": {"layer": "crystallized", "source_memory_ids": ["s2"]},
            },
            {"id": "low", "memory": "Low score", "score": 0.40, "metadata": {"layer": "raw"}},
        ]

        block = _format_memories(
            results,
            limit=3,
            max_chars=800,
            minimum_score=0.50,
            score_margin=0.15,
            max_crystallized=1,
        )

        self.assertIn("raw-1", block)
        self.assertIn("crystal-1", block)
        self.assertNotIn("crystal-2", block)
        self.assertNotIn("Low score", block)
        self.assertIn("&lt;unsafe&gt;", block)
        self.assertTrue(block.endswith("</long_term_memory>"))
        self.assertLessEqual(len(block), 800)
        self.assertIn("explicit approval", block)

    def test_follow_up_reuses_and_reinjects_cached_recall(self) -> None:
        fake = _FakeMcpClient(
            {"results": [{"id": "m1", "memory": "Keep the rollback plan.", "score": 0.9}]}
        )
        context = ToolContext(workspace_root=self.workspace)
        context.session_id = "session-123"
        context.mcp_clients = {"latent-memory": fake}
        config = PassiveMemoryConfig(enabled=True, human_id="chen")

        first_prompt, _ = _run(
            prepare_top_level_run(
                [UserMessage(content="Plan a PostgreSQL migration with rollback checks.")],
                "base",
                context,
                config=config,
            )
        )
        second_prompt, _ = _run(
            prepare_top_level_run(
                [
                    UserMessage(content="Plan a PostgreSQL migration with rollback checks."),
                    AssistantMessage(content=[TextBlock(text="Here is the plan.")]),
                    UserMessage(content="Please proceed with that plan."),
                ],
                "base",
                context,
                config=config,
            )
        )

        self.assertEqual(len(fake.calls), 1)
        self.assertIn("Keep the rollback plan", first_prompt)
        self.assertIn("Keep the rollback plan", second_prompt)
        self.assertTrue(fake.calls[0][1]["rerank"])

    def test_different_top_level_runs_do_not_share_recall_cache(self) -> None:
        fake = _FakeMcpClient(
            {"results": [{"id": "m1", "memory": "Run-specific result.", "score": 0.9}]}
        )
        config = PassiveMemoryConfig(enabled=True, human_id="chen")

        for session_id in ("session-123", "session-456"):
            context = ToolContext(workspace_root=self.workspace)
            context.session_id = session_id
            context.mcp_clients = {"latent-memory": fake}
            _run(
                prepare_top_level_run(
                    [UserMessage(content="Please answer the same wrapped benchmark question.")],
                    "base",
                    context,
                    config=config,
                )
            )

        self.assertEqual(len(fake.calls), 2)

    def test_confirmation_with_a_new_topic_refreshes_recall(self) -> None:
        self.assertTrue(
            _should_refresh_recall(
                "Plan the PostgreSQL database migration.",
                "I confirm. Now search hotels in Paris.",
            )
        )

    def test_capture_uses_complete_business_turn_and_excludes_thinking(self) -> None:
        messages = [
            UserMessage(content="Remember that tests use pytest."),
            AssistantMessage(
                content=[
                    ThinkingBlock(thinking="private reasoning"),
                    TextBlock(text="I will verify it."),
                    ToolUseBlock(id="tool-1", name="Bash", input={"command": "pytest"}),
                ]
            ),
            UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id="tool-1",
                        content="3 passed",
                        is_error=False,
                    )
                ],
                origin="tool_result",
            ),
            AssistantMessage(content=[TextBlock(text="The pytest suite passes.")]),
        ]

        payload, strength = build_capture_messages(messages, max_tokens=8000)
        serialized = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(strength, "strong")
        self.assertIn("3 passed", serialized)
        self.assertIn("The pytest suite passes", serialized)
        self.assertNotIn("private reasoning", serialized)

    def test_completed_capture_writes_all_three_ids(self) -> None:
        context = ToolContext(workspace_root=self.workspace)
        client = PassiveMemoryMcpClient(context, "latent-memory")
        run = PassiveMemoryRun(
            config=PassiveMemoryConfig(enabled=True),
            ids=MemoryIds(
                user_id="ccx:chen:project:repo-12345678",
                agent_id="ccx:primary",
                run_id="ccxrun:session-123",
                project_key="repo-12345678",
            ),
            client=client,
            user_prompt="Remember this",
        )
        messages = [
            UserMessage(content="Remember this preference."),
            AssistantMessage(content=[TextBlock(text="Preference confirmed.")]),
        ]

        with patch("clawcodex_ext.latent_memory.passive.lifecycle.enqueue_memory_write") as enqueue:
            complete_top_level_run(run, messages, terminal_reason="completed")

        arguments = enqueue.call_args.args[1]
        self.assertEqual(arguments["user_id"], run.ids.user_id)
        self.assertEqual(arguments["agent_id"], run.ids.agent_id)
        self.assertEqual(arguments["run_id"], run.ids.run_id)


class TestPassiveMemoryEntrypoints(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.temp_dir.name)
        self.registry = build_default_registry()
        self.context = ToolContext(workspace_root=self.workspace)
        # 安装被动记忆插件（注册 on_query_start / on_query_end 钩子）
        from clawcodex_ext.latent_memory.plugin import install_passive_memory_plugin

        install_passive_memory_plugin()

    def tearDown(self) -> None:
        # 清理钩子注册表，避免测试间污染
        from clawcodex_ext.query.hook_registry import unregister_loop_hook

        unregister_loop_hook("passive_memory_recall", "on_query_start")
        unregister_loop_hook("passive_memory_capture", "on_query_end")
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    def _provider(self) -> MagicMock:
        provider = MagicMock()
        provider.chat_stream_response.side_effect = NotImplementedError()
        provider.chat.return_value = ChatResponse(
            content="Done.",
            model="test",
            usage={"input_tokens": 10, "output_tokens": 5},
            finish_reason="end_turn",
            tool_uses=None,
        )
        return provider

    def test_query_engine_calls_passive_lifecycle_once(self) -> None:
        marker = object()
        prepare = AsyncMock(return_value=("prompt with memory", marker))
        complete = MagicMock()
        engine = QueryEngine(
            QueryEngineConfig(
                cwd=self.workspace,
                provider=self._provider(),
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

        prepare.assert_awaited_once()
        complete.assert_called_once()
        self.assertIs(complete.call_args.args[0], marker)

    def test_agent_loop_adapter_calls_passive_lifecycle_once(self) -> None:
        marker = object()
        prepare = AsyncMock(return_value=("prompt with memory", marker))
        complete = MagicMock()

        with (
            patch("clawcodex_ext.latent_memory.passive.prepare_top_level_run", prepare),
            patch("clawcodex_ext.latent_memory.passive.complete_top_level_run", complete),
        ):
            result = _run(
                run_query_as_agent_loop(
                    initial_messages=[UserMessage(content="Implement it")],
                    provider=self._provider(),
                    tool_registry=self.registry,
                    tool_context=self.context,
                    system_prompt="base prompt",
                    max_turns=5,
                )
            )

        self.assertEqual(result.terminal.reason, "completed")
        prepare.assert_awaited_once()
        complete.assert_called_once()
        self.assertIs(complete.call_args.args[0], marker)


if __name__ == "__main__":
    unittest.main()
