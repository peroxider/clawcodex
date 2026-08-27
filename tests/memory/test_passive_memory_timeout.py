from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clawcodex_ext.latent_memory.passive.config import PassiveMemoryConfig
from clawcodex_ext.latent_memory.passive.lifecycle import prepare_top_level_run
from clawcodex_ext.latent_memory.passive.mcp_client import PassiveMemoryMcpClient
from clawcodex_ext.services.mcp.client import McpClient
from clawcodex_ext.services.mcp.errors import McpToolCallError
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.types.messages import UserMessage


class _SlowMcpClient:
    def __init__(self) -> None:
        self.cancelled = threading.Event()

    async def call_tool(self, name: str, arguments: dict):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _PendingTransport:
    def __init__(self) -> None:
        self.sent = asyncio.Event()

    async def send(self, message) -> None:
        self.sent.set()


class TestPassiveMemoryTimeout(unittest.TestCase):
    def test_default_search_timeout_is_five_seconds(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAWCODEX_PASSIVE_MEMORY_SEARCH_TIMEOUT_MS", None)
            config = PassiveMemoryConfig.from_env()

        self.assertEqual(config.search_timeout_ms, 5000)

    def test_search_timeout_cancels_real_mcp_coroutine(self) -> None:
        async def scenario() -> tuple[bool, float]:
            slow_client = _SlowMcpClient()
            owner_loop = asyncio.new_event_loop()
            context = SimpleNamespace(
                mcp_clients={"latent-memory": slow_client},
                mcp_manager_loop=owner_loop,
            )
            client = PassiveMemoryMcpClient(context, "latent-memory")
            started_at = time.monotonic()
            try:
                with self.assertRaises(asyncio.TimeoutError):
                    await client.search({}, timeout_seconds=0.02)
            finally:
                owner_loop.close()
            return slow_client.cancelled.is_set(), time.monotonic() - started_at

        cancelled, elapsed = asyncio.run(scenario())

        self.assertTrue(cancelled)
        self.assertLess(elapsed, 1.0)

    def test_cancelled_mcp_request_is_removed_from_pending_map(self) -> None:
        async def scenario() -> dict:
            client = McpClient()
            transport = _PendingTransport()
            client._transport = transport
            task = asyncio.create_task(client._send_request("tools/call", {}))
            await transport.sent.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            return client._pending_requests

        self.assertEqual(asyncio.run(scenario()), {})

    def test_recall_timeout_is_logged_as_graceful_degradation(self) -> None:
        context = ToolContext(workspace_root=Path.cwd())
        context.session_id = "timeout-test"
        context.mcp_clients = {"latent-memory": object()}
        config = PassiveMemoryConfig(
            enabled=True,
            human_id="test-user",
            search_timeout_ms=123,
        )
        search = AsyncMock(side_effect=asyncio.TimeoutError)

        with (
            patch.object(PassiveMemoryMcpClient, "search", search),
            self.assertLogs("clawcodex_ext.latent_memory.passive.lifecycle", level="INFO") as logs,
        ):
            _, run = asyncio.run(
                prepare_top_level_run(
                    [UserMessage(content="Design the database layer")],
                    "base prompt",
                    context,
                    config=config,
                )
            )

        self.assertIsNone(run)
        self.assertIn("event=recall_timeout", "\n".join(logs.output))
        self.assertIn("event=memory_server_unavailable", "\n".join(logs.output))
        self.assertNotIn("event=recall_failed", "\n".join(logs.output))
        self.assertEqual(search.await_args.kwargs["timeout_seconds"], 0.123)

    def test_unreachable_server_warns_once_without_traceback(self) -> None:
        context = ToolContext(workspace_root=Path.cwd())
        context.session_id = "offline-test"
        context.mcp_clients = {"offline-memory": object()}
        config = PassiveMemoryConfig(
            enabled=True,
            human_id="test-user",
            server_name="offline-memory",
        )
        search = AsyncMock(
            side_effect=McpToolCallError(
                "MemoryServerError: connection failed: [WinError 10061] actively refused"
            )
        )

        with (
            patch.object(PassiveMemoryMcpClient, "search", search),
            self.assertLogs(
                "clawcodex_ext.latent_memory.passive.lifecycle", level="WARNING"
            ) as logs,
        ):
            first = asyncio.run(
                prepare_top_level_run(
                    [UserMessage(content="Remember the database choice")],
                    "base prompt",
                    context,
                    config=config,
                )
            )
            second = asyncio.run(
                prepare_top_level_run(
                    [UserMessage(content="Recall the database choice")],
                    "base prompt",
                    context,
                    config=config,
                )
            )

        output = "\n".join(logs.output)
        self.assertIsNone(first[1])
        self.assertIsNone(second[1])
        self.assertEqual(output.count("event=memory_server_unavailable"), 1)
        self.assertNotIn("Traceback", output)
