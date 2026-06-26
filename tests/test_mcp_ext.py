"""Tests for MCP 增强功能模块 (:mod:`clawcodex_ext.mcp_ext`).

Covers:
- MCP 资源缓存 (cache hit/miss, TTL eviction, LRU eviction, invalidation)
- MCP Batch 工具调用 (happy path, partial failures, validation)
- MCP Progress 通知 (extraction, wrapping)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from clawcodex_ext.mcp_ext import (
    McpBatchCallTool,
    _cache_get,
    _cache_invalidate,
    _cache_set,
    _MCP_RESOURCE_CACHE,
    configure_mcp_cache,
    extract_mcp_progress,
    wrap_mcp_call_with_progress,
    wrap_mcp_list_resources_call,
    wrap_mcp_resource_call,
)
from src.tool_system.context import ToolContext
from clawcodex_ext.tool_system.protocol import ToolResult


# ============================================================================
# 1. MCP 资源缓存
# ============================================================================


class TestMcpResourceCache:
    def teardown_method(self) -> None:
        _cache_invalidate()  # clear all

    def test_cache_set_and_get(self) -> None:
        tr = ToolResult(name="Read", output={"contents": "data"})
        _cache_set("s1", "uri:foo", tr)
        cached = _cache_get("s1", "uri:foo")
        assert cached is tr

    def test_cache_miss_returns_none(self) -> None:
        assert _cache_get("nonexistent", "uri:missing") is None

    def test_cache_ttl_expiry(self) -> None:
        configure_mcp_cache(ttl=0.01, max_entries=128)
        tr = ToolResult(name="Read", output={"contents": "data"})
        _cache_set("s1", "uri:bar", tr)
        assert _cache_get("s1", "uri:bar") is tr
        time.sleep(0.02)
        assert _cache_get("s1", "uri:bar") is None
        configure_mcp_cache(ttl=60.0)  # restore

    def test_cache_lru_eviction(self) -> None:
        configure_mcp_cache(ttl=300, max_entries=3)
        for i in range(4):
            tr = ToolResult(name="R", output={"i": i})
            _cache_set("s", f"uri:{i}", tr)
        # The first entry (i=0) should be evicted
        assert _cache_get("s", "uri:0") is None
        assert _cache_get("s", "uri:3") is not None
        configure_mcp_cache(max_entries=128)

    def test_cache_invalidate_all(self) -> None:
        _cache_set("s1", "uri:a", ToolResult(name="R", output={}))
        _cache_set("s2", "uri:b", ToolResult(name="R", output={}))
        _cache_invalidate()
        assert len(_MCP_RESOURCE_CACHE) == 0

    def test_cache_invalidate_by_server(self) -> None:
        _cache_set("s1", "uri:a", ToolResult(name="R", output={}))
        _cache_set("s1", "uri:b", ToolResult(name="R", output={}))
        _cache_set("s2", "uri:c", ToolResult(name="R", output={}))
        _cache_invalidate(server="s1")
        assert _cache_get("s1", "uri:a") is None
        assert _cache_get("s1", "uri:b") is None
        assert _cache_get("s2", "uri:c") is not None

    def test_wrap_resource_call_caches_result(self) -> None:
        call_count = 0

        def original(tool_input: dict, ctx: ToolContext) -> ToolResult:
            nonlocal call_count
            call_count += 1
            return ToolResult(name="Read", output={"contents": "data"})

        wrapped = wrap_mcp_resource_call(original)

        ctx = MagicMock(spec=ToolContext)
        inp = {"server": "s1", "uri": "u1"}
        r1 = wrapped(inp, ctx)
        r2 = wrapped(inp, ctx)
        # Original called only once; second hit served from cache.
        assert call_count == 1
        assert r1.output == r2.output

    def test_wrap_resource_call_skips_cache_on_error(self) -> None:
        call_count = 0

        def original(tool_input: dict, ctx: ToolContext) -> ToolResult:
            nonlocal call_count
            call_count += 1
            return ToolResult(name="Read", output={"error": "fail"}, is_error=True)

        wrapped = wrap_mcp_resource_call(original)

        ctx = MagicMock(spec=ToolContext)
        inp = {"server": "s1", "uri": "u1"}
        wrapped(inp, ctx)
        wrapped(inp, ctx)
        # Error results should NOT be cached.
        assert call_count == 2

    def test_wrap_list_resources_call_caches(self) -> None:
        call_count = 0

        def original(tool_input: dict, ctx: ToolContext) -> ToolResult:
            nonlocal call_count
            call_count += 1
            return ToolResult(name="List", output=[{"uri": "r1"}])

        wrapped = wrap_mcp_list_resources_call(original)

        ctx = MagicMock(spec=ToolContext)
        inp = {"server": "s1"}
        r1 = wrapped(inp, ctx)
        r2 = wrapped(inp, ctx)
        assert call_count == 1
        assert r1.output == r2.output


# ============================================================================
# 2. MCP Batch 工具调用
# ============================================================================


class TestMcpBatchCall:
    def test_batch_happy_path(self) -> None:
        client1 = MagicMock()
        client1.call_tool.side_effect = [{"result": "ok1"}, {"result": "ok2"}]

        ctx = MagicMock(spec=ToolContext)
        ctx.mcp_clients = {"github": client1}

        result = McpBatchCallTool.call(
            {
                "calls": [
                    {"server": "github", "tool": "get_issue", "input": {"id": 1}},
                    {"server": "github", "tool": "list_comments", "input": {"id": 1}},
                ]
            },
            ctx,
        )
        assert not result.is_error
        assert result.output["succeeded"] == 2
        assert result.output["failed"] == 0
        assert len(result.output["results"]) == 2

    def test_batch_partial_failure(self) -> None:
        client1 = MagicMock()
        client1.call_tool.side_effect = [{"result": "ok"}, ValueError("boom")]

        ctx = MagicMock(spec=ToolContext)
        ctx.mcp_clients = {"github": client1}

        result = McpBatchCallTool.call(
            {
                "calls": [
                    {"server": "github", "tool": "good_tool", "input": {}},
                    {"server": "github", "tool": "bad_tool", "input": {}},
                ]
            },
            ctx,
        )
        assert result.output["succeeded"] == 1
        assert result.output["failed"] == 1
        assert len(result.output["errors"]) == 1

    def test_batch_unknown_server(self) -> None:
        ctx = MagicMock(spec=ToolContext)
        ctx.mcp_clients = {}

        result = McpBatchCallTool.call(
            {"calls": [{"server": "unknown", "tool": "foo", "input": {}}]},
            ctx,
        )
        assert result.output["succeeded"] == 0
        assert result.output["failed"] == 1

    def test_batch_raises_on_empty_calls(self) -> None:
        ctx = MagicMock(spec=ToolContext)
        with pytest.raises(Exception):
            McpBatchCallTool.call({"calls": []}, ctx)

    def test_batch_raises_on_invalid_call_spec(self) -> None:
        ctx = MagicMock(spec=ToolContext)
        result = McpBatchCallTool.call(
            {"calls": [{"server": "", "tool": "foo"}]},
            ctx,
        )
        assert result.output["failed"] == 1


# ============================================================================
# 3. MCP Progress 通知
# ============================================================================


class TestMcpProgress:
    def test_extract_progress_dict(self) -> None:
        events: list[tuple[int, int | None]] = []

        def on_progress(p: int, t: int | None) -> None:
            events.append((p, t))

        response = {"progress": 50, "totalProgress": 100, "data": "ok"}
        result = extract_mcp_progress(response, on_progress=on_progress)
        assert events == [(50, 100)]
        # progress/totalProgress should still be in the response
        # (extraction is read-only — the caller decides what to forward)
        assert result["data"] == "ok"

    def test_extract_progress_no_total(self) -> None:
        events: list[tuple[int, int | None]] = []

        def on_progress(p: int, t: int | None) -> None:
            events.append((p, t))

        extract_mcp_progress({"progress": 10}, on_progress=on_progress)
        assert events == [(10, None)]

    def test_extract_progress_list(self) -> None:
        events: list[tuple[int, int | None]] = []

        def on_progress(p: int, t: int | None) -> None:
            events.append((p, t))

        extract_mcp_progress(
            [{"progress": 1, "totalProgress": 5}, {"progress": 3, "totalProgress": 5}],
            on_progress=on_progress,
        )
        assert events == [(1, 5), (3, 5)]

    def test_wrap_call_with_progress_invokes_callback(self) -> None:
        events: list[tuple[int, int | None]] = []

        def original(tool_input: dict, ctx: ToolContext) -> ToolResult:
            return ToolResult(
                name="MCP",
                output={
                    "server": "s1",
                    "tool": "long_task",
                    "output": {"progress": 75, "totalProgress": 100, "result": "done"},
                },
            )

        wrapped = wrap_mcp_call_with_progress(original)

        ctx = MagicMock(spec=ToolContext)
        ctx.on_mcp_progress = lambda p, t: events.append((p, t))

        wrapped({"server": "s1", "tool": "long_task"}, ctx)
        assert (75, 100) in events

    def test_wrap_call_no_progress_callback(self) -> None:
        """No crash when on_mcp_progress is absent."""
        ctx = MagicMock(spec=ToolContext)
        # Remove the attribute so getattr returns None
        if hasattr(ctx, "on_mcp_progress"):
            del ctx.on_mcp_progress

        wrapped = wrap_mcp_call_with_progress(
            lambda inp, ctx: ToolResult(name="MCP", output={"output": "ok"})
        )
        result = wrapped({"server": "s1", "tool": "t"}, ctx)
        assert not result.is_error
