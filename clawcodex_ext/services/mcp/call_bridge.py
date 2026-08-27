"""Thread-safe helpers for driving MCP clients on their owner event loop."""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_LOCKS_GUARD = threading.Lock()
_LOOP_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, threading.RLock] = (
    weakref.WeakKeyDictionary()
)

# ---------------------------------------------------------------------------
# MCP tool-argument interceptor pipeline
# ---------------------------------------------------------------------------
# Generic, plugin-extensible callbacks that can inspect/modify tool arguments
# before every MCP tool call.  Plugins (e.g. passive memory) register their
# handlers here at install time so that the MCP tool wrappers remain free of
# feature-specific imports.
#
# Signature: (args, *, server_name, tool_name, input_schema, context) -> args
# ---------------------------------------------------------------------------

McpArgInterceptor = Callable[..., dict[str, Any]]
_MCP_ARG_INTERCEPTORS: list[McpArgInterceptor] = []


def register_mcp_arg_interceptor(fn: McpArgInterceptor) -> None:
    """Register a callback that runs before every MCP tool call."""
    if fn not in _MCP_ARG_INTERCEPTORS:
        _MCP_ARG_INTERCEPTORS.append(fn)


def unregister_mcp_arg_interceptor(fn: McpArgInterceptor) -> None:
    """Unregister a previously registered MCP argument interceptor."""
    try:
        _MCP_ARG_INTERCEPTORS.remove(fn)
    except ValueError:
        pass


def run_mcp_arg_interceptors(
    args: dict[str, Any],
    *,
    server_name: str,
    tool_name: str,
    input_schema: dict[str, Any] | None = None,
    context: Any = None,
) -> dict[str, Any]:
    """Run all registered interceptors and return the (possibly modified) args."""
    for fn in _MCP_ARG_INTERCEPTORS:
        try:
            result = fn(
                args,
                server_name=server_name,
                tool_name=tool_name,
                input_schema=input_schema,
                context=context,
            )
            if isinstance(result, dict):
                args = result
        except Exception:
            logger.debug(
                "MCP arg interceptor %r failed", getattr(fn, "__name__", fn), exc_info=True
            )
    return args


def _loop_lock(loop: asyncio.AbstractEventLoop) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOOP_LOCKS.get(loop)
        if lock is None:
            lock = threading.RLock()
            _LOOP_LOCKS[loop] = lock
        return lock


def run_mcp_coro(
    coro: Coroutine[Any, Any, Any],
    owner_loop: asyncio.AbstractEventLoop | None,
) -> Any:
    """Run *coro* without concurrently driving an MCP transport loop."""
    if owner_loop is None or owner_loop.is_closed():
        return _run_on_fresh_loop(coro)

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is owner_loop:
        coro.close()
        raise RuntimeError("Cannot synchronously drive the active MCP owner loop")

    with _loop_lock(owner_loop):
        if owner_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, owner_loop)
            return future.result()
        return owner_loop.run_until_complete(coro)


def _run_on_fresh_loop(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


__all__ = [
    "run_mcp_coro",
    "register_mcp_arg_interceptor",
    "run_mcp_arg_interceptors",
    "unregister_mcp_arg_interceptor",
]
