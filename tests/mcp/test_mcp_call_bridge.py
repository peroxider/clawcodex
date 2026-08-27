from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from clawcodex_ext.services.mcp.call_bridge import run_mcp_coro


def test_stopped_owner_loop_is_serialized_across_threads() -> None:
    loop = asyncio.new_event_loop()
    active = 0
    maximum_active = 0

    async def work(value: int) -> int:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return value

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run_mcp_coro, work(value), loop) for value in (1, 2)]
            assert sorted(future.result(timeout=2) for future in futures) == [1, 2]
    finally:
        loop.close()

    assert maximum_active == 1


def test_running_owner_loop_executes_on_owner_thread() -> None:
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    owner_thread_id: list[int] = []

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        owner_thread_id.append(threading.get_ident())
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    assert ready.wait(timeout=2)

    async def identify_thread() -> int:
        return threading.get_ident()

    try:
        assert run_mcp_coro(identify_thread(), loop) == owner_thread_id[0]
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


def test_owner_loop_cannot_be_synchronously_driven_from_itself() -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        with pytest.raises(RuntimeError, match="active MCP owner loop"):
            run_mcp_coro(asyncio.sleep(0), loop)

    asyncio.run(scenario())


def test_fresh_loop_path_uses_worker_when_called_inside_asyncio() -> None:
    async def identify_thread() -> int:
        return threading.get_ident()

    async def scenario() -> tuple[int, int]:
        caller = threading.get_ident()
        worker = run_mcp_coro(identify_thread(), None)
        return caller, worker

    caller_thread, worker_thread = asyncio.run(scenario())
    assert worker_thread != caller_thread
