#!/usr/bin/env python
"""Terminal monitor for the <long_term_memory> block injected into agent requests.

Two modes
---------
``run``
    Launch the clawcodex agent with tracing enabled. Monkey-patches
    ``prepare_top_level_run`` (to capture injection context) and
    ``_call_model_sync`` (to capture the EXACT system_prompt that is
    handed to the LLM provider). The block displayed in the monitor
    is extracted from the ``_call_model_sync`` argument, so it is
    byte-for-byte identical to what the agent actually receives.

``watch``
    Real-time TUI that tails the trace file and shows every injected
    block plus a verification badge confirming whether the block
    reached the LLM call.

Usage
-----
    # Terminal 1 — start the agent with tracing
    python scripts/debug/memory_monitor.py run -- <any clawcodex-dev args>

    # Terminal 2 — open the monitor window
    python scripts/debug/memory_monitor.py watch

    # Inspect history as plain text
    python scripts/debug/memory_monitor.py show [--last N]

    # Clear the trace file
    python scripts/debug/memory_monitor.py clear

Environment
-----------
    CLAWCODEX_LTM_TRACE_FILE
        Override the trace file path (default: ~/.clawcodex/memory_trace.jsonl).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# --- Configuration --------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE_FILE = Path(
    os.environ.get(
        "CLAWCODEX_LTM_TRACE_FILE",
        str(Path.home() / ".clawcodex" / "memory_trace.jsonl"),
    )
)

LTM_BLOCK_RE = re.compile(
    r"<long_term_memory>.*?</long_term_memory>",
    re.DOTALL,
)


def _trace_path(args: argparse.Namespace) -> Path:
    if getattr(args, "trace_file", None):
        return Path(args.trace_file).expanduser()
    return DEFAULT_TRACE_FILE


def _write_trace(event: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _system_prompt_len(sp: Any) -> int:
    if isinstance(sp, str):
        return len(sp)
    if isinstance(sp, list):
        return sum(len(b.get("text", "")) for b in sp if isinstance(b, dict))
    return 0


def _system_prompt_hash(sp: Any) -> str:
    if isinstance(sp, str):
        data = sp.encode("utf-8")
    elif isinstance(sp, list):
        data = json.dumps(sp, ensure_ascii=False, sort_keys=True).encode("utf-8")
    else:
        data = str(sp).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def _extract_ltm_block(sp: Any) -> str | None:
    """Extract the last <long_term_memory>...</long_term_memory> block
    from a system_prompt value (str or list[dict]).

    This is the source of truth for what the agent receives: it is
    extracted from the actual argument of ``_call_model_sync``.
    """
    if isinstance(sp, str):
        matches = LTM_BLOCK_RE.findall(sp)
        return matches[-1] if matches else None
    if isinstance(sp, list):
        for item in reversed(sp):
            if isinstance(item, dict):
                text = item.get("text", "") or ""
                if "<long_term_memory>" in text:
                    matches = LTM_BLOCK_RE.findall(text)
                    if matches:
                        return matches[-1]
    return None


# --- Patches --------------------------------------------------------------


def install_patches(trace_path: Path) -> None:
    """Monkey-patch the passive-memory lifecycle and the LLM call path
    to capture the EXACT system_prompt handed to the provider.

    Two interception points:
      1. ``prepare_top_level_run`` — captures injection context
         (run_id, user query, prompt preview, block as injected).
      2. ``_call_model_sync`` — captures the system_prompt that is
         literally passed to the LLM provider (after any pre_llm
         hook modifications). This is the authoritative source for
         "what the agent actually received".

    Patch visibility note
    ---------------------
    ``engine.py`` and ``agent_loop_compat.py`` both import via
    ``from clawcodex_ext.latent_memory.passive import prepare_top_level_run``
    — i.e. they resolve the name through the **package __init__**,
    not through the ``lifecycle`` submodule. The package __init__
    caches its own reference at import time, so patching only
    ``lifecycle.prepare_top_level_run`` is invisible to those
    callers. We therefore patch BOTH modules: ``lifecycle`` (for
    any code that imports from there directly) and the package
    ``__init__`` (the path the engine actually uses).
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    import clawcodex_ext.latent_memory.passive as passive_pkg
    from clawcodex_ext.latent_memory.passive import lifecycle
    from clawcodex_ext.latent_memory.passive.message_utils import (
        build_search_query,
        latest_user_prompt,
    )
    from clawcodex_ext.query import query as query_module

    # --- Patch 1: prepare_top_level_run (context capture) ----------------
    _orig_prepare = lifecycle.prepare_top_level_run

    async def _traced_prepare(messages, system_prompt, tool_context, **kwargs):
        started_at = time.monotonic()
        prompt = ""
        query = ""
        try:
            prompt = latest_user_prompt(messages) or ""
            query = build_search_query(messages) or ""
        except Exception:
            pass

        _write_trace(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "event": "prepare_start",
                "prompt_preview": prompt[:300],
                "query": query[:800],
                "system_prompt_type": type(system_prompt).__name__,
            },
            trace_path,
        )

        try:
            new_sp, run = await _orig_prepare(messages, system_prompt, tool_context, **kwargs)
        except Exception as exc:
            _write_trace(
                {
                    "ts": datetime.now().isoformat(timespec="milliseconds"),
                    "event": "prepare_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                trace_path,
            )
            raise

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        injected_block = _extract_ltm_block(new_sp)
        run_id = getattr(getattr(run, "ids", None), "run_id", None) if run else None

        _write_trace(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "event": "prepare_end",
                "run_id": run_id,
                "prompt_preview": prompt[:300],
                "query": query[:800],
                "elapsed_ms": elapsed_ms,
                "injected": injected_block is not None,
                "injected_block_chars": len(injected_block) if injected_block else 0,
                "final_prompt_chars": _system_prompt_len(new_sp),
                "final_prompt_hash": _system_prompt_hash(new_sp),
                "system_prompt_type": type(new_sp).__name__,
                "block": injected_block,
            },
            trace_path,
        )

        return new_sp, run

    lifecycle.prepare_top_level_run = _traced_prepare
    # engine.py / agent_loop_compat.py resolve the name through the
    # package __init__, so we MUST also replace it there — otherwise
    # the patch is invisible to the real call sites.
    passive_pkg.prepare_top_level_run = _traced_prepare

    # --- Patch 2: _call_model_sync (authoritative LLM input) -------------
    _orig_call = query_module._call_model_sync

    async def _traced_call(*args, **kwargs):
        # This is the LAST stop before the LLM provider is called.
        # The system_prompt here is exactly what the agent receives
        # (post pre_llm hooks, post compression, post everything).
        system_prompt = kwargs.get("system_prompt", "")
        block = _extract_ltm_block(system_prompt)
        _write_trace(
            {
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "event": "llm_call",
                "system_prompt_chars": _system_prompt_len(system_prompt),
                "system_prompt_hash": _system_prompt_hash(system_prompt),
                "system_prompt_type": type(system_prompt).__name__,
                "has_ltm_block": block is not None,
                "block_chars": len(block) if block else 0,
                "block_hash": hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
                if block
                else None,
                "block": block,
            },
            trace_path,
        )

        return await _orig_call(*args, **kwargs)

    query_module._call_model_sync = _traced_call


# --- Commands -------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    trace_path = _trace_path(args)

    if args.fresh and trace_path.exists():
        trace_path.unlink()

    install_patches(trace_path)

    # Hand off to the agent CLI. Strip our own subcommand so the agent
    # sees the remaining args as if it were launched directly.
    passthrough = list(args.agent_args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    sys.argv = [sys.argv[0]] + passthrough

    # Enable verbose passive-memory logging to stderr for correlation.
    os.environ.setdefault("CLAWCODEX_PASSIVE_MEMORY_LOG_LEVEL", "DEBUG")

    sys.stderr.write(f"[memory_monitor] trace file: {trace_path}\n")
    sys.stderr.write(f"[memory_monitor] launching agent with {len(passthrough)} passthrough args\n")
    sys.stderr.flush()

    try:
        from clawcodex_ext.cli.main import main as agent_main
    except ImportError as exc:
        sys.stderr.write(
            f"[memory_monitor] failed to import clawcodex_ext: {exc}\n"
            f"[memory_monitor] ensure clawcodex is installed "
            f"(pip install -e {REPO_ROOT})\n"
        )
        return 2

    return int(agent_main() or 0)


def cmd_watch(args: argparse.Namespace) -> int:
    trace_path = _trace_path(args)

    try:
        from rich.console import Console
        from rich.layout import Layout
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        sys.stderr.write(
            "[memory_monitor] 'rich' is required for watch mode. Install: pip install rich\n"
        )
        return 2

    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if not trace_path.exists():
        trace_path.touch()

    sys.stderr.write(f"[memory_monitor] watching: {trace_path}\n")
    sys.stderr.write("[memory_monitor] press Ctrl+C to exit\n")
    sys.stderr.flush()
    time.sleep(0.4)

    console = Console()
    events: list[dict] = []
    max_events = 500
    offset = 0

    def _read_new() -> None:
        nonlocal offset, events
        try:
            size = trace_path.stat().st_size
            if size < offset:
                # File was truncated/rotated
                offset = 0
                events = []
            with trace_path.open("r", encoding="utf-8") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if len(events) > max_events:
            events = events[-max_events:]

    def _find_latest_inject():
        for i in range(len(events) - 1, -1, -1):
            e = events[i]
            if e.get("event") == "prepare_end" and e.get("injected"):
                return e, i
        return None, -1

    def _find_latest_llm_with_block(after_idx: int = -1):
        start = after_idx + 1 if after_idx >= 0 else 0
        for i in range(len(events) - 1, start - 1, -1):
            e = events[i]
            if e.get("event") == "llm_call" and e.get("has_ltm_block"):
                return e
        return None

    def _count_llm_calls_with_block(block_hash: str | None) -> int:
        if not block_hash:
            return 0
        return sum(
            1 for e in events if e.get("event") == "llm_call" and e.get("block_hash") == block_hash
        )

    try:
        with Live(console=console, refresh_per_second=4, screen=True) as live:
            while True:
                _read_new()

                # Header / stats
                prepares = [e for e in events if e.get("event") == "prepare_end"]
                injected = [e for e in prepares if e.get("injected")]
                skipped = [e for e in prepares if not e.get("injected")]
                errors = [e for e in events if e.get("event") == "prepare_error"]
                llm_calls = [e for e in events if e.get("event") == "llm_call"]
                llm_with_block = [e for e in llm_calls if e.get("has_ltm_block")]
                llm_without_block = [e for e in llm_calls if not e.get("has_ltm_block")]

                layout = Layout()
                layout.split_column(
                    Layout(name="header", size=3),
                    Layout(name="block", ratio=3),
                    Layout(name="history", ratio=2),
                )

                header_text = (
                    "[bold cyan]LTM Block Monitor[/]  "
                    f"[dim]{trace_path}[/]\n"
                    f"prepares={len(prepares)} injected={len(injected)} "
                    f"skipped={len(skipped)} errors={len(errors)}  |  "
                    f"llm_calls={len(llm_calls)} "
                    f"with_block={len(llm_with_block)} "
                    f"without_block={len(llm_without_block)}  "
                    "[dim]Ctrl+C to exit[/]"
                )
                layout["header"].update(Panel(header_text, style="blue", border_style="blue"))

                # Latest injected block (authoritative: extracted from
                # the _call_model_sync argument, not from prepare_top_level_run)
                latest_llm = _find_latest_llm_with_block()
                latest_prepare, prepare_idx = _find_latest_inject()

                if latest_llm:
                    block_text = latest_llm.get("block", "") or ""
                    block_hash = latest_llm.get("block_hash")
                    calls_with = _count_llm_calls_with_block(block_hash)

                    title_parts = [
                        f"VERIFIED @ {latest_llm.get('ts', '?')[:23]}",
                        f"chars={latest_llm.get('block_chars', 0)}",
                        f"sp_hash={latest_llm.get('system_prompt_hash', '?')}",
                        f"used_in={calls_with}_llm_calls",
                    ]
                    if latest_prepare:
                        title_parts.append(f"run={latest_prepare.get('run_id', '?')[:32]}")
                        title_parts.append(f"query={(latest_prepare.get('query', '') or '')[:60]}")

                    content = Text()
                    content.append(
                        "✓ EXTRACTED FROM _call_model_sync(system_prompt=...) "
                        "— identical to what the LLM provider receives\n",
                        style="bold green",
                    )
                    content.append(
                        f"system_prompt_chars={latest_llm.get('system_prompt_chars', 0)}  "
                        f"type={latest_llm.get('system_prompt_type', '?')}  "
                        f"block_hash={block_hash}\n\n",
                        style="dim",
                    )
                    content.append(block_text, style="white")

                    layout["block"].update(
                        Panel(
                            content,
                            title="  |  ".join(title_parts),
                            border_style="green",
                        )
                    )
                elif latest_prepare:
                    # prepare injected but no llm_call captured yet (or block
                    # was stripped between prepare and llm_call)
                    block = latest_prepare.get("block", "") or ""
                    content = Text()
                    content.append(
                        "⚠ INJECTED by prepare_top_level_run but NOT seen in "
                        "any _call_model_sync call yet\n",
                        style="bold yellow",
                    )
                    content.append(
                        f"Possible causes: pre_llm hook stripped the block, "
                        f"agent hasn't made an LLM call yet, or block was "
                        f"removed by compression.\n\n",
                        style="yellow",
                    )
                    content.append(block, style="white")
                    layout["block"].update(
                        Panel(
                            content,
                            title=f"INJECTED-BUT-UNVERIFIED @ {latest_prepare.get('ts', '?')[:23]}",
                            border_style="yellow",
                        )
                    )
                else:
                    layout["block"].update(
                        Panel(
                            "[dim]Waiting for the first <long_term_memory> block...\n"
                            "Run the agent with: "
                            "python scripts/debug/memory_monitor.py run[/dim]",
                            title="No block yet",
                            border_style="dim",
                        )
                    )

                # History table
                table = Table(show_header=True, header_style="bold", expand=True)
                table.add_column("Time", width=12, no_wrap=True)
                table.add_column("Event", width=14, no_wrap=True)
                table.add_column("Detail", no_wrap=False)

                for e in events[-15:]:
                    ts = (e.get("ts", "") or "")[11:23]
                    ev = e.get("event", "")
                    if ev == "prepare_start":
                        query = (e.get("query", "") or "")[:60]
                        detail = f"[dim]query={query}[/dim]"
                    elif ev == "prepare_end":
                        if e.get("injected"):
                            detail = (
                                f"[green]INJECT[/green] "
                                f"chars={e.get('injected_block_chars', 0)} "
                                f"final={e.get('final_prompt_chars', 0)} "
                                f"elapsed={e.get('elapsed_ms', '?')}ms "
                                f"run={(e.get('run_id') or '?')[:24]}"
                            )
                        else:
                            detail = (
                                f"[yellow]SKIP[/yellow] "
                                f"elapsed={e.get('elapsed_ms', '?')}ms "
                                f"run={(e.get('run_id') or '?')[:24]}"
                            )
                    elif ev == "llm_call":
                        if e.get("has_ltm_block"):
                            detail = (
                                f"[green]LLM+block[/green] "
                                f"sp_chars={e.get('system_prompt_chars', 0)} "
                                f"block_chars={e.get('block_chars', 0)} "
                                f"hash={e.get('block_hash', '?')[:8]}"
                            )
                        else:
                            detail = (
                                f"[red]LLM no-block[/red] "
                                f"sp_chars={e.get('system_prompt_chars', 0)}"
                            )
                    elif ev == "prepare_error":
                        detail = (
                            f"[red]ERROR {e.get('error_type', '?')}: "
                            f"{e.get('error', '')[:60]}[/red]"
                        )
                    else:
                        detail = ""
                    table.add_row(ts, ev, detail)

                layout["history"].update(
                    Panel(
                        table,
                        title=f"History (last {min(15, len(events))} of {len(events)})",
                        border_style="cyan",
                    )
                )

                live.update(layout)
                time.sleep(0.25)
    except KeyboardInterrupt:
        sys.stderr.write("\n[memory_monitor] stopped\n")
        return 0


def cmd_show(args: argparse.Namespace) -> int:
    trace_path = _trace_path(args)
    if not trace_path.exists():
        sys.stderr.write(f"[memory_monitor] trace file not found: {trace_path}\n")
        return 1

    events = []
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if args.last:
        events = events[-args.last :]

    for e in events:
        ev = e.get("event", "?")
        ts = e.get("ts", "?")
        print(f"=== {ts}  {ev} ===")
        if ev == "prepare_start":
            print(f"  query:    {(e.get('query') or '')[:200]}")
            print(f"  prompt:   {(e.get('prompt_preview') or '')[:200]}")
        elif ev == "prepare_end":
            print(f"  run_id:        {e.get('run_id', '?')}")
            print(f"  injected:      {e.get('injected', '?')}")
            print(f"  block_chars:   {e.get('injected_block_chars', 0)}")
            print(f"  final_chars:   {e.get('final_prompt_chars', 0)}")
            print(f"  final_hash:    {e.get('final_prompt_hash', '?')}")
            print(f"  elapsed_ms:    {e.get('elapsed_ms', '?')}")
            print(f"  query:         {(e.get('query') or '')[:200]}")
            block = e.get("block")
            if block:
                print("  --- injected block ---")
                print(block)
                print("  --- end block ---")
        elif ev == "llm_call":
            print(f"  sp_chars:      {e.get('system_prompt_chars', 0)}")
            print(f"  sp_hash:       {e.get('system_prompt_hash', '?')}")
            print(f"  has_ltm_block: {e.get('has_ltm_block', '?')}")
            print(f"  block_chars:   {e.get('block_chars', 0)}")
            print(f"  block_hash:    {e.get('block_hash', '?')}")
            block = e.get("block")
            if block:
                print("  --- block (extracted from _call_model_sync arg) ---")
                print(block)
                print("  --- end block ---")
        elif ev == "prepare_error":
            print(f"  error: {e.get('error_type', '?')}: {e.get('error', '')}")
        print()
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    trace_path = _trace_path(args)
    if trace_path.exists():
        trace_path.unlink()
        sys.stderr.write(f"[memory_monitor] cleared: {trace_path}\n")
    else:
        sys.stderr.write(f"[memory_monitor] nothing to clear: {trace_path}\n")
    return 0


# --- Main -----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitor <long_term_memory> blocks injected into agent requests.",
    )
    parser.add_argument(
        "--trace-file",
        default=None,
        help=f"Trace file path (default: {DEFAULT_TRACE_FILE})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Launch the agent with tracing enabled")
    p_run.add_argument(
        "--fresh",
        action="store_true",
        help="Clear the trace file before launching",
    )
    p_run.add_argument(
        "agent_args",
        nargs=argparse.REMAINDER,
        help="Args passed to the agent (use -- to separate)",
    )
    p_run.set_defaults(func=cmd_run)

    p_watch = sub.add_parser("watch", help="Real-time TUI that tails the trace file")
    p_watch.set_defaults(func=cmd_watch)

    p_show = sub.add_parser("show", help="Dump all captured events to stdout")
    p_show.add_argument("--last", type=int, default=None, help="Show only last N events")
    p_show.set_defaults(func=cmd_show)

    p_clear = sub.add_parser("clear", help="Clear the trace file")
    p_clear.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
