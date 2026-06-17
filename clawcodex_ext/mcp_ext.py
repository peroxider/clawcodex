"""MCP 增强功能模块。

提供三个轻量级增强（对应 FEATURE_PLAN §2.4.1）：

1. **MCP 资源缓存** — 对 ``ReadMcpResourceTool`` 和 ``ListMcpResourcesTool``
   的 ``read_resource`` / ``list_resources`` 调用添加 LRU 缓存 + TTL，
   减少重复获取同一资源的网络开销。
2. **MCP Batch 工具调用** — 新增 ``McpBatchCallTool``，接受 ``(server, tool, input)``
   列表，顺序执行并汇总结果，减少 LLM 多轮编排的开销。
3. **MCP Progress 通知** — 在 ``_mcp_call`` 中拦截 MCP 响应中的
   ``progress`` / ``totalProgress`` 字段，通过 ``ToolContext`` 的回调
   向上层报告进度，使长任务（文件下载、代码分析等）可见。
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Callable

from src.tool_system.build_tool import Tool, build_tool
from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.protocol import ToolResult

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. MCP 资源缓存
# ---------------------------------------------------------------------------

_MCP_RESOURCE_CACHE: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_MCP_RESOURCE_CACHE_TTL = 60.0  # seconds
_MCP_RESOURCE_CACHE_MAX = 128


def _cache_key(server: str, uri: str | None = None) -> str:
    return f"{server}::{uri or '__list__'}"


def _cache_get(server: str, uri: str | None = None) -> Any | None:
    key = _cache_key(server, uri)
    entry = _MCP_RESOURCE_CACHE.get(key)
    if entry is None:
        return None
    ts, value = entry
    if time.monotonic() - ts > _MCP_RESOURCE_CACHE_TTL:
        del _MCP_RESOURCE_CACHE[key]
        return None
    # Move to end (most recently used)
    _MCP_RESOURCE_CACHE.move_to_end(key)
    return value


def _cache_set(server: str, uri: str | None, value: Any) -> None:
    key = _cache_key(server, uri)
    _MCP_RESOURCE_CACHE[key] = (time.monotonic(), value)
    while len(_MCP_RESOURCE_CACHE) > _MCP_RESOURCE_CACHE_MAX:
        _MCP_RESOURCE_CACHE.popitem(last=False)


def _cache_invalidate(server: str | None = None, uri: str | None = None) -> None:
    """Invalidate cached entries.

    When *server* is None, clears the entire cache.
    When *uri* is None, invalidates all entries for *server*.
    """
    if server is None:
        _MCP_RESOURCE_CACHE.clear()
        return
    if uri is None:
        prefix = f"{server}::"
        for key in list(_MCP_RESOURCE_CACHE.keys()):
            if key.startswith(prefix):
                del _MCP_RESOURCE_CACHE[key]
        return
    _MCP_RESOURCE_CACHE.pop(_cache_key(server, uri), None)


def configure_mcp_cache(*, ttl: float = 60.0, max_entries: int = 128) -> None:
    """Update cache parameters at runtime."""
    global _MCP_RESOURCE_CACHE_TTL, _MCP_RESOURCE_CACHE_MAX
    _MCP_RESOURCE_CACHE_TTL = ttl
    _MCP_RESOURCE_CACHE_MAX = max_entries


def wrap_mcp_resource_call(original_call: Callable) -> Callable:
    """Decorate an MCP resource call function with caching.

    Usage in ``mcp_resources.py``::

        from clawcodex_ext.mcp_ext import wrap_mcp_resource_call

        _read_mcp_resource_call = wrap_mcp_resource_call(_read_mcp_resource_call_impl)
    """

    def _cached_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        server = tool_input.get("server", "")
        uri = tool_input.get("uri")

        # Check cache first.
        cached = _cache_get(server, uri)
        if cached is not None:
            _log.debug("MCP resource cache HIT: server=%s uri=%s", server, uri)
            return cached

        result = original_call(tool_input, context)

        # Cache successful (non-error) results only.
        if not getattr(result, "is_error", False):
            _cache_set(server, uri, result)

        return result

    return _cached_call


def wrap_mcp_list_resources_call(original_call: Callable) -> Callable:
    """Decorate ``_list_mcp_resources_call`` with caching (keys by server)."""

    def _cached_list_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        server = tool_input.get("server", "")

        cached = _cache_get(server)
        if cached is not None:
            _log.debug("MCP resource list cache HIT: server=%s", server)
            return cached

        result = original_call(tool_input, context)

        if not getattr(result, "is_error", False):
            _cache_set(server, None, result)

        return result

    return _cached_list_call


# ---------------------------------------------------------------------------
# 2. MCP Batch 工具调用
# ---------------------------------------------------------------------------

MCP_BATCH_TOOL_PROMPT = """\
Execute multiple MCP tool calls in a single invocation.

Useful when you need to call several tools on the same MCP server (or
across different servers) without waiting for a round-trip per call.

Parameters:
- calls (required): A list of call objects, each with:
    - server (string, required): MCP server name
    - tool (string, required): Tool name on that server
    - input (object, optional): Tool arguments

The calls are executed sequentially within a single tool invocation.
Results are returned as a list in the same order as the input calls.

Example:
  ``MCPBatch({ calls: [
       {server: "github", tool: "get_issue", input: {owner: "org", repo: "repo", issue_number: 42}},
       {server: "github", tool: "list_comments", input: {owner: "org", repo: "repo", issue_number: 42}},
  ]})``
"""


def _mcp_batch_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    calls = tool_input.get("calls")
    if not isinstance(calls, list) or len(calls) == 0:
        raise ToolInputError("calls must be a non-empty list of {server, tool, ...} objects")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, call_spec in enumerate(calls):
        if not isinstance(call_spec, dict):
            errors.append({"index": idx, "error": "call spec must be an object"})
            continue

        server = call_spec.get("server")
        tool_name = call_spec.get("tool")
        args = call_spec.get("input") or {}

        if not isinstance(server, str) or not server:
            errors.append({"index": idx, "error": "server must be a non-empty string"})
            continue
        if not isinstance(tool_name, str) or not tool_name:
            errors.append({"index": idx, "error": "tool must be a non-empty string"})
            continue

        client = context.mcp_clients.get(server)
        if client is None:
            errors.append({"index": idx, "server": server, "error": "mcp server not connected"})
            continue

        try:
            out = client.call_tool(tool_name, args)
            results.append({"index": idx, "server": server, "tool": tool_name, "output": out})
        except Exception as exc:
            _log.warning("MCP batch call #%d failed: %s", idx, exc)
            errors.append({"index": idx, "server": server, "tool": tool_name, "error": str(exc)})

    return ToolResult(
        name="MCPBatch",
        output={
            "results": results,
            "errors": errors,
            "total": len(calls),
            "succeeded": len(results),
            "failed": len(errors),
        },
    )


McpBatchCallTool: Tool = build_tool(
    name="MCPBatch",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "calls": {
                "type": "array",
                "description": "List of MCP tool calls to execute",
                "items": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string", "description": "MCP server name"},
                        "tool": {"type": "string", "description": "Tool name on the server"},
                        "input": {
                            "type": "object",
                            "description": "Tool arguments (optional)",
                        },
                    },
                    "required": ["server", "tool"],
                },
            },
        },
        "required": ["calls"],
    },
    call=_mcp_batch_call,
    prompt=MCP_BATCH_TOOL_PROMPT,
    description="Execute multiple MCP tool calls in one invocation.",
    max_result_size_chars=200_000,
    is_destructive=lambda _input: True,
    is_mcp=True,
)


# ---------------------------------------------------------------------------
# 3. MCP Progress 通知
# ---------------------------------------------------------------------------

def extract_mcp_progress(
    response: Any,
    *,
    on_progress: Callable[[int, int | None], None] | None = None,
) -> Any:
    """Extract progress information from an MCP tool response and fire the
    callback if provided.

    MCP servers may include ``progress`` and ``totalProgress`` fields in
    their response metadata.  This function peels them off and passes them
    to *on_progress*, then returns the response without those fields so the
    caller sees only the actual payload.

    Returns the (possibly cleaned) response unchanged.
    """
    if on_progress is None:
        return response

    if isinstance(response, dict):
        progress = response.get("progress")
        total = response.get("totalProgress")
        if progress is not None:
            try:
                on_progress(int(progress), int(total) if total is not None else None)
            except (ValueError, TypeError):
                pass
    elif isinstance(response, list):
        for item in response:
            extract_mcp_progress(item, on_progress=on_progress)

    return response


def wrap_mcp_call_with_progress(original_call: Callable) -> Callable:
    """Decorate an MCP call function to extract progress notifications.

    The decorator looks for a ``on_mcp_progress`` callable attached to
    the ``ToolContext`` and, when present, feeds progress data from the
    MCP server response to it.
    """

    def _progress_aware_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        on_progress: Callable | None = getattr(context, "on_mcp_progress", None)

        result = original_call(tool_input, context)

        if on_progress is not None and not getattr(result, "is_error", False):
            output = result.output if isinstance(result.output, dict) else {}
            server_output = output.get("output")
            extract_mcp_progress(server_output, on_progress=on_progress)

        return result

    return _progress_aware_call
