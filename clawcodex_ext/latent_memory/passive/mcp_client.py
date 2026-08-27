from __future__ import annotations

import asyncio
import atexit
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from clawcodex_ext.services.mcp.call_bridge import run_mcp_coro


logger = logging.getLogger(__name__)


class PassiveMemoryMcpClient:
    def __init__(self, tool_context: Any, server_name: str) -> None:
        self._context = tool_context
        self._server_name = server_name

    @property
    def available(self) -> bool:
        clients = getattr(self._context, "mcp_clients", None) or {}
        return self._server_name in clients

    async def search(
        self,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(
            self.call_tool_sync,
            "memory_search",
            arguments,
            timeout_seconds=timeout_seconds,
        )
        payload = _result_payload(result)
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            return [item for item in payload["results"] if isinstance(item, dict)]
        return []

    def call_tool_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        clients = getattr(self._context, "mcp_clients", None) or {}
        client = clients.get(self._server_name)
        if client is None:
            raise RuntimeError(f"MCP server not connected: {self._server_name}")

        async def invoke() -> Any:
            call = client.call_tool(tool_name, arguments)
            if timeout_seconds is None:
                return await call
            return await asyncio.wait_for(call, timeout=max(0.0, timeout_seconds))

        return run_mcp_coro(invoke(), getattr(self._context, "mcp_manager_loop", None))


@dataclass(frozen=True)
class _WriteJob:
    client: PassiveMemoryMcpClient
    arguments: dict[str, Any]


class _MemoryWriteQueue:
    def __init__(self, max_size: int) -> None:
        self._queue: queue.Queue[_WriteJob | None] = queue.Queue(maxsize=max_size)
        self._thread = threading.Thread(
            target=self._run,
            name="clawcodex-passive-memory",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, job: _WriteJob) -> None:
        event_id = _event_id(job)
        try:
            self._queue.put_nowait(job)
            logger.debug(
                "event=write_enqueued event_id=%s queue_size=%d",
                event_id,
                self._queue.qsize(),
            )
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(job)
            logger.warning(
                "event=write_queue_replaced_oldest event_id=%s queue_size=%d",
                event_id,
                self._queue.qsize(),
            )
        except queue.Full:
            logger.warning("event=write_dropped reason=queue_full event_id=%s", event_id)

    def flush(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        logger.debug(
            "event=flush_started unfinished=%d timeout_seconds=%.1f",
            self._queue.unfinished_tasks,
            timeout,
        )
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        complete = self._queue.unfinished_tasks == 0
        if complete:
            logger.debug("event=flush_completed")
        else:
            logger.warning(
                "event=flush_timeout unfinished=%d timeout_seconds=%.1f",
                self._queue.unfinished_tasks,
                timeout,
            )
        return complete

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is None:
                    return
                event_id = _event_id(job)
                started_at = time.monotonic()
                logger.debug("event=write_started event_id=%s", event_id)
                result = job.client.call_tool_sync("memory_add_messages", job.arguments)
                payload = _result_payload(result)
                status, result_count = _write_result_summary(payload)
                logger.info(
                    "event=write_completed event_id=%s status=%s result_count=%s elapsed_ms=%d",
                    event_id,
                    status,
                    result_count,
                    int((time.monotonic() - started_at) * 1000),
                )
            except Exception as exc:
                message = " ".join(str(exc).split()) or type(exc).__name__
                if len(message) > 300:
                    message = f"{message[:297]}..."
                logger.warning(
                    "event=write_failed event_id=%s error=%s",
                    _event_id(job) if job is not None else "unknown",
                    message,
                )
            finally:
                self._queue.task_done()


_WRITER_LOCK = threading.Lock()
_WRITER: _MemoryWriteQueue | None = None


def enqueue_memory_write(
    client: PassiveMemoryMcpClient,
    arguments: dict[str, Any],
    *,
    max_queue_size: int,
) -> None:
    global _WRITER
    with _WRITER_LOCK:
        if _WRITER is None:
            _WRITER = _MemoryWriteQueue(max_queue_size)
    _WRITER.enqueue(_WriteJob(client=client, arguments=arguments))


def flush_pending_writes(timeout: float = 10.0) -> bool:
    writer = _WRITER
    return True if writer is None else writer.flush(timeout)


def _result_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", result)
    if isinstance(content, dict):
        return content
    texts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                texts.append(block)
    elif isinstance(content, str):
        texts.append(content)
    text = "\n".join(texts).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _event_id(job: _WriteJob) -> str:
    metadata = job.arguments.get("metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("event_id") or "unknown")
    return "unknown"


def _write_result_summary(payload: Any) -> tuple[str, int | str]:
    if not isinstance(payload, dict):
        return "unknown", "unknown"
    status = str(payload.get("status") or "ok")
    results = payload.get("results")
    return status, len(results) if isinstance(results, list) else "unknown"


atexit.register(lambda: flush_pending_writes(10.0))


__all__ = [
    "PassiveMemoryMcpClient",
    "enqueue_memory_write",
    "flush_pending_writes",
]
