from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def test_memory_monitor_forwards_current_runtime_arguments(tmp_path: Path) -> None:
    import clawcodex_ext.latent_memory.passive as passive_pkg
    from clawcodex_ext.latent_memory.passive import lifecycle
    from clawcodex_ext.query import query
    from scripts.debug import memory_monitor

    original_lifecycle_prepare = lifecycle.prepare_top_level_run
    original_package_prepare = passive_pkg.prepare_top_level_run
    original_call = query._call_model_sync
    received: dict[str, dict[str, Any]] = {}

    async def fake_prepare(messages, system_prompt, tool_context, **kwargs):
        received["prepare"] = kwargs
        return system_prompt + "\n<long_term_memory>remembered</long_term_memory>", None

    async def fake_call(*args, **kwargs):
        received["call"] = kwargs
        return [], []

    trace_path = tmp_path / "trace.jsonl"
    try:
        lifecycle.prepare_top_level_run = fake_prepare
        passive_pkg.prepare_top_level_run = fake_prepare
        query._call_model_sync = fake_call
        memory_monitor.install_patches(trace_path)

        async def exercise_patches() -> None:
            await lifecycle.prepare_top_level_run(
                [], "", None, recall_query="explicit recall query"
            )
            await query._call_model_sync(
                provider=None,
                messages=[],
                system_prompt="<long_term_memory>remembered</long_term_memory>",
                tools=None,
                extended_thinking=True,
                thinking_effort="high",
                sdk_max_retries=0,
            )

        asyncio.run(exercise_patches())
    finally:
        lifecycle.prepare_top_level_run = original_lifecycle_prepare
        passive_pkg.prepare_top_level_run = original_package_prepare
        query._call_model_sync = original_call

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert received["prepare"]["recall_query"] == "explicit recall query"
    assert received["call"]["extended_thinking"] is True
    assert received["call"]["thinking_effort"] == "high"
    assert received["call"]["sdk_max_retries"] == 0
    assert [event["event"] for event in events] == [
        "prepare_start",
        "prepare_end",
        "llm_call",
    ]
    assert events[-1]["has_ltm_block"] is True


def test_repl_pty_wrapper_help_works_outside_repository(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    script = repository / "scripts" / "latent_memory" / "repl_pty_session.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Control the real ClawCodex REPL through a PTY" in completed.stdout
