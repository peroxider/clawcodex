"""Tests for F-REC-L real REPL capture (extensions.recording.repl_source).

These tests use lightweight fake REPL objects so they do not need to
spin up the full :class:`ClawCodexExtREPL` (which would require a
provider, session, and tool registry). The fake objects expose exactly
the public attributes ``install_repl_capture`` patches:
``repl.console`` and ``repl.prompt_session``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from prompt_toolkit import PromptSession
from rich.console import Console

from extensions.capabilities.recorder import AsciicastEvent
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.repl_source import (
    PromptSessionProxy,
    RichConsoleTeeWriter,
    install_repl_capture,
)
from extensions.recording.validate_cast import validate_cast


def _make_event(kind: str, data: str) -> AsciicastEvent:
    return AsciicastEvent(t=0.0, kind=kind, data=data)  # type: ignore[arg-type]


@dataclass
class _FakeCtx:
    """Minimal runtime context for install_repl_capture."""

    options: argparse.Namespace = field(
        default_factory=lambda: argparse.Namespace()
    )


@dataclass
class _FakeREPL:
    console: Console
    prompt_session: Any


# ---------------------------------------------------------------------------
# RichConsoleTeeWriter
# ---------------------------------------------------------------------------


def test_tee_writer_forwards_to_original_and_capture(
    tmp_path: Path,
) -> None:
    """Every write hits both the real stream and the capture sink."""
    captured: list[str] = []
    original = sys.stdout
    tee = RichConsoleTeeWriter(original, captured.append)

    tee.write("hello")
    assert "hello" in captured


def test_tee_writer_silently_drops_sink_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """A broken capture sink must not break the upstream console print."""
    def _boom(_data: str) -> None:
        raise RuntimeError("sink broken")

    tee = RichConsoleTeeWriter(sys.stdout, _boom)
    # Should not raise.
    written = tee.write("still visible")
    assert written > 0
    assert "still visible" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# PromptSessionProxy
# ---------------------------------------------------------------------------


async def _drive_proxy(proxy: PromptSessionProxy, value: str | None) -> Any:
    """Async helper so tests can await prompt_async."""
    return await proxy.prompt_async("❯ ")


def test_proxy_emits_markers_and_input_frame(tmp_path: Path) -> None:
    """prompt_async emits start marker, i-frame, and submit marker."""
    capture = Mock(spec=["marker", "emit"])
    emitted: list[tuple[str, str]] = []

    def _emit(event: Any) -> None:
        emitted.append((event.kind, event.data))

    capture.marker = lambda label: emitted.append(("m", label))
    capture.emit = _emit

    real_session = Mock()
    real_session.prompt_async = lambda *a, **k: asyncio.sleep(0, result="hello")
    proxy = PromptSessionProxy(
        real_session, capture, emit_i=lambda d: _emit(_make_event("i", d))
    )

    result = asyncio.run(_drive_proxy(proxy, "ignored"))
    assert result == "hello"

    labels = [data for kind, data in emitted if kind == "m"]
    assert labels == ["repl:prompt:start", "repl:prompt:submit"]
    inputs = [data for kind, data in emitted if kind == "i"]
    assert inputs == ["hello\n"]


def test_proxy_does_not_emit_input_for_none(tmp_path: Path) -> None:
    """Ctrl-C / Ctrl-D returns None; no input frame should be written."""
    capture = Mock(spec=["marker", "emit"])
    emitted: list[tuple[str, str]] = []
    capture.marker = lambda label: emitted.append(("m", label))
    capture.emit = lambda event: emitted.append((event.kind, event.data))

    real_session = Mock()
    real_session.prompt_async = lambda *a, **k: asyncio.sleep(0, result=None)
    proxy = PromptSessionProxy(
        real_session,
        capture,
        emit_i=lambda d: capture.emit(_make_event("i", d)),
    )

    result = asyncio.run(_drive_proxy(proxy, "ignored"))
    assert result is None
    assert all(kind != "i" for kind, _ in emitted)


class MockEvent:
    def __init__(self, kind: str, data: str) -> None:
        self.kind = kind
        self.data = data


# ---------------------------------------------------------------------------
# install_repl_capture integration
# ---------------------------------------------------------------------------


def test_install_repl_capture_returns_writer_and_writes_rich_output(
    tmp_path: Path,
) -> None:
    """End-to-end: patched console.print → .cast with ANSI + validate OK."""
    console = Console(theme=None, highlight=False)
    repl = _FakeREPL(
        console=console,
        prompt_session=PromptSession(),
    )
    out = tmp_path / "real.cast"
    ctx = _FakeCtx()
    ctx.options.record = str(out)
    ctx.options.record_width = 120
    ctx.options.record_height = 36

    writer = install_repl_capture(repl, ctx)
    assert writer is not None
    assert isinstance(writer, AsciicastWriter)

    # Simulate the REPL printing agent output.
    repl.console.print("[bold]Agent:[/bold] hello")
    writer.close()

    assert validate_cast(out) == []

    raw = out.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    assert header["width"] == 120
    assert header["height"] == 36
    # Output frame must contain ANSI escape sequences from Rich.
    o_frames = [json.loads(line) for line in raw[1:] if line.strip()]
    assert any(f[1] == "o" and "\x1b[" in f[2] for f in o_frames)


def test_install_repl_capture_prompt_proxy_records_input(
    tmp_path: Path,
) -> None:
    """prompt_async through the proxy records an 'i' frame."""
    console = Console(theme=None, highlight=False)
    repl = _FakeREPL(
        console=console,
        prompt_session=PromptSession(),
    )
    out = tmp_path / "input.cast"
    ctx = _FakeCtx()
    ctx.options.record = str(out)

    writer = install_repl_capture(repl, ctx)
    assert writer is not None

    async def _drive() -> None:
        return await repl.prompt_session.prompt_async("❯ ")

    real_session = Mock()
    real_session.prompt_async = lambda *a, **k: asyncio.sleep(0, result="run tests")
    repl.prompt_session = PromptSessionProxy(
        real_session,
        writer.capture,
        emit_i=lambda d: writer.capture.emit(_make_event("i", d)),
    )

    result = asyncio.run(_drive())
    assert result == "run tests"
    writer.close()

    raw = out.read_text(encoding="utf-8").splitlines()
    frames = [json.loads(line) for line in raw[1:] if line.strip()]
    assert any(f[1] == "i" and "run tests" in f[2] for f in frames)


def test_install_repl_capture_does_not_break_console_printing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The user still sees console output even while recording."""
    console = Console(theme=None, highlight=False)
    repl = _FakeREPL(
        console=console,
        prompt_session=PromptSession(),
    )
    out = tmp_path / "visible.cast"
    ctx = _FakeCtx()
    ctx.options.record = str(out)

    writer = install_repl_capture(repl, ctx)
    assert writer is not None
    repl.console.print("[success]visible[/success]")
    writer.close()

    assert "visible" in capsys.readouterr().out


def test_install_repl_capture_disabled_when_no_record_option(
    tmp_path: Path,
) -> None:
    """If ctx.options.record is unset, install_repl_capture returns None."""
    console = Console(theme=None, highlight=False)
    repl = _FakeREPL(
        console=console,
        prompt_session=PromptSession(),
    )
    ctx = _FakeCtx()
    writer = install_repl_capture(repl, ctx)
    assert writer is None


def test_install_repl_capture_missing_prompt_session_is_ok(
    tmp_path: Path,
) -> None:
    """Some REPL construction paths set prompt_session late; capture should
    still patch console and leave session alone."""
    console = Console(theme=None, highlight=False)
    repl = _FakeREPL(console=console, prompt_session=None)
    out = tmp_path / "no_session.cast"
    ctx = _FakeCtx()
    ctx.options.record = str(out)

    writer = install_repl_capture(repl, ctx)
    assert writer is not None
    repl.console.print("ok")
    writer.close()
    assert validate_cast(out) == []
