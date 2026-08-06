"""REPL capture E2E driver: record a lightweight but real REPL-like capture.

This module is **not** a simulated dashboard demo — it exercises the
real capture wiring from :mod:`extensions.recording.repl_source`:

* a real :class:`rich.console.Console`,
* a real :class:`prompt_toolkit.PromptSession`,
* the :func:`install_repl_capture` hook,
* and real ANSI output from Rich.

The only thing that is mocked is the REPL loop itself: instead of
running ``ClawCodexExtREPL.run()`` (which would need a provider, session,
and agent), we drive a minimal object that has exactly the two public
attributes ``install_repl_capture`` needs: ``console`` and
``prompt_session``.

Usage::

    python3 -m extensions.recording.examples.repl_demo_driver \
        --out /tmp/real-repl.cast

The produced ``.cast`` is self-validated and contains:

* ``"o"`` frames with real ANSI escape sequences (Rich markup),
* ``"i"`` frames with the user input captured by ``PromptSessionProxy``,
* ``"m"`` markers at ``repl:prompt:start`` / ``repl:prompt:submit``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console

from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.repl_source import install_repl_capture
from extensions.recording.validate_cast import validate_cast


@dataclass
class _FakeRuntimeContext:
    """Minimal object with ``options.record`` so install_repl_capture can read it."""

    options: argparse.Namespace = field(default_factory=lambda: argparse.Namespace())


@dataclass
class _FakeREPL:
    """Public surface that install_repl_capture needs to patch."""

    console: Console
    prompt_session: Any


async def _simulate_interaction(repl: _FakeREPL) -> None:
    """Drive the prompt session twice and emit some Rich output.

    This is async because ``PromptSessionProxy.prompt_async`` is async.
    """
    # First prompt: user asks for an explanation.
    user_input_1 = await repl.prompt_session.prompt_async("❯ ")
    repl.console.print(f"[bold]User:[/bold] {user_input_1}")
    repl.console.print(
        "[success]Agent:[/success] Here is the layout:\n"
        "  src/          upstream Claude Code\n"
        "  clawcodex_ext/ downstream patches\n"
        "  extensions/    third-party extensions"
    )

    # Second prompt: a command-style input.
    user_input_2 = await repl.prompt_session.prompt_async("❯ ")
    repl.console.print(f"[bold]User:[/bold] {user_input_2}")
    repl.console.print(
        "[info]Agent:[/info] Running that now...\n"
        "[dim]  tool: Bash -> ls -la[/dim]\n"
        "[dim]  ...[/dim]"
    )


def run(out_path: Path, *, width: int = 120, height: int = 36) -> int:
    """Drive the demo and write a .cast file. Returns process exit code."""
    out_path = Path(out_path).expanduser().resolve()

    # Build the same kind of objects a real REPL would have.
    console = Console(theme=None, highlight=False)
    prompt_session: Any = PromptSession()
    repl = _FakeREPL(console=console, prompt_session=prompt_session)

    ctx = _FakeRuntimeContext()
    ctx.options.record = str(out_path)
    ctx.options.record_width = width
    ctx.options.record_height = height

    writer = install_repl_capture(repl, ctx)
    if writer is None:
        print("[demo] recording was not enabled", file=sys.stderr)
        return 1

    # Drive the fake REPL loop.
    try:
        asyncio.run(_simulate_interaction(repl))
    finally:
        writer.close()

    # Self-validate so a copy-paste run gives immediate feedback.
    errors = validate_cast(out_path)
    if errors:
        print(f"[demo] validation FAILED for {out_path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"[demo] {out_path} — {writer.frame_count} frame(s); "
        f"validation: OK"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="repl-demo-driver",
        description=(
            "Drive a lightweight but real REPL-like capture through "
            "extensions.recording.repl_source. Produces a .cast file "
            "containing real Rich ANSI output and captured input frames."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("real-repl-demo.cast"),
        help="Output .cast file path (default: %(default)s).",
    )
    p.add_argument(
        "--width",
        type=int,
        default=120,
        help="Terminal width for the .cast header (default: %(default)s).",
    )
    p.add_argument(
        "--height",
        type=int,
        default=36,
        help="Terminal height for the .cast header (default: %(default)s).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run(args.out, width=args.width, height=args.height)


if __name__ == "__main__":
    raise SystemExit(main())
