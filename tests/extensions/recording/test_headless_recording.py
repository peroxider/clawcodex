"""Tests for F-REC-H headless agent-loop recording.

Lightweight unit + integration tests for :class:`HeadlessRecorder` and its
wiring into ``run_headless``. These tests do not need a configured provider
or a real agent loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from clawcodex_ext.tool_system.renderers import ToolEvent
from extensions.capabilities.recorder import AsciicastCapture
from extensions.recording.headless_source import (
    HeadlessRecorder,
    open_headless_recorder,
)
from extensions.recording.validate_cast import validate_cast


def _cast_lines(path: Path) -> list[dict | list]:
    """Parse a .cast file into header + frame payloads."""
    lines = path.read_text(encoding="utf-8").splitlines()
    result: list[dict | list] = []
    for line in lines:
        if not line.strip():
            continue
        result.append(json.loads(line))
    return result


def test_recorder_opens_and_emits_session_markers(tmp_path: Path) -> None:
    out = tmp_path / "session.cast"
    recorder = open_headless_recorder(out)
    capture = recorder.__enter__()
    assert capture is not None
    assert isinstance(capture, AsciicastCapture)
    recorder.__exit__(None, None, None)

    lines = _cast_lines(out)
    assert lines[0]["version"] == 2
    assert lines[0]["width"] > 0
    assert lines[0]["height"] > 0
    assert validate_cast(out) == []

    markers = [line[2] for line in lines[1:] if line[1] == "m"]
    assert "session:start" in markers
    assert "session:end" in markers


def test_recorder_emits_input_frame(tmp_path: Path) -> None:
    out = tmp_path / "input.cast"
    recorder = open_headless_recorder(out)
    recorder.__enter__()
    recorder.emit_input("hello")
    recorder.__exit__(None, None, None)

    inputs = [line[2] for line in _cast_lines(out)[1:] if line[1] == "i"]
    assert inputs == ["hello\n"]


def test_recorder_emits_text_frame(tmp_path: Path) -> None:
    out = tmp_path / "text.cast"
    recorder = open_headless_recorder(out)
    recorder.__enter__()
    recorder.emit_text("world")
    recorder.__exit__(None, None, None)

    outputs = [line[2] for line in _cast_lines(out)[1:] if line[1] == "o"]
    assert "world" in outputs


def test_recorder_emits_tool_use_frame(tmp_path: Path) -> None:
    out = tmp_path / "tool.cast"
    recorder = open_headless_recorder(out)
    recorder.__enter__()
    recorder.emit_tool_event(
        ToolEvent(
            kind="tool_use",
            tool_name="Bash",
            tool_input={"cmd": "ls"},
            tool_use_id="tu_1",
        )
    )
    recorder.__exit__(None, None, None)

    outputs = [line[2] for line in _cast_lines(out)[1:] if line[1] == "o"]
    assert any("Tool Use: Bash" in s for s in outputs)
    assert any("ls" in s for s in outputs)


def test_recorder_emits_tool_result_frame(tmp_path: Path) -> None:
    out = tmp_path / "result.cast"
    recorder = open_headless_recorder(out)
    recorder.__enter__()
    recorder.emit_tool_event(
        ToolEvent(
            kind="tool_result",
            tool_name="Bash",
            tool_output={"exit_code": 0, "stdout": "ok"},
            tool_use_id="tu_1",
        )
    )
    recorder.__exit__(None, None, None)

    outputs = [line[2] for line in _cast_lines(out)[1:] if line[1] == "o"]
    assert any("Tool Result: Bash" in s for s in outputs)


def test_recorder_swallows_emit_errors(tmp_path: Path) -> None:
    """A broken capture sink must not propagate exceptions."""
    out = tmp_path / "broken.cast"
    recorder = open_headless_recorder(out)
    capture = Mock(spec=AsciicastCapture)
    capture.marker.side_effect = RuntimeError("marker broken")
    capture.emit.side_effect = RuntimeError("emit broken")
    recorder.capture = capture
    recorder._start = 0.0

    recorder.emit_input("hi")
    recorder.emit_text("hello")
    recorder.emit_tool_event(
        ToolEvent(kind="tool_use", tool_name="Read", tool_input={})
    )
    recorder.__exit__(None, None, None)


def test_recorder_skips_empty_input_and_text() -> None:
    """Empty strings produce no frames."""
    out = Path("/dev/null")
    recorder = open_headless_recorder(out)
    recorder.capture = Mock(spec=AsciicastCapture)
    recorder._start = 0.0

    recorder.emit_input("")
    recorder.emit_text("")
    recorder.capture.emit.assert_not_called()


def test_recorder_closes_on_exception(tmp_path: Path) -> None:
    out = tmp_path / "exc.cast"
    recorder = open_headless_recorder(out)
    recorder.__enter__()
    with pytest.raises(RuntimeError):
        with recorder:
            raise RuntimeError("boom")

    assert validate_cast(out) == []
    markers = [line[2] for line in _cast_lines(out)[1:] if line[1] == "m"]
    assert "session:start" in markers
    assert "session:end" in markers


def test_open_headless_recorder_respects_width_height(tmp_path: Path) -> None:
    out = tmp_path / "size.cast"
    recorder = open_headless_recorder(out, width=80, height=25)
    recorder.__enter__()
    recorder.__exit__(None, None, None)

    header = _cast_lines(out)[0]
    assert header["width"] == 80
    assert header["height"] == 25


def test_run_headless_passes_capture_to_agent_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch _run_headless_core to verify the recorder is opened and passed."""
    from clawcodex_ext.entrypoints.headless import HeadlessOptions, run_headless

    captured: dict[str, Any] = {}

    def _fake_core(options: HeadlessOptions) -> int:
        captured["capture"] = options.capture
        captured["record"] = options.record
        return 0

    monkeypatch.setattr(
        "clawcodex_ext.entrypoints.headless._run_headless_core", _fake_core
    )

    out = tmp_path / "via_run.cast"
    rc = run_headless(
        HeadlessOptions(
            prompt="hi",
            record=str(out),
            record_width=100,
            record_height=30,
            persist_on_exit=False,
        )
    )
    assert rc == 0
    assert captured["record"] == str(out)
    assert captured["capture"] is not None
    # Writer was closed by run_headless finally.
    assert out.exists()
    assert validate_cast(out) == []
    header = _cast_lines(out)[0]
    assert header["width"] == 100
    assert header["height"] == 30


def test_run_headless_without_record_does_not_open_recorder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from clawcodex_ext.entrypoints.headless import HeadlessOptions, run_headless

    captured: dict[str, Any] = {}

    def _fake_core(options: HeadlessOptions) -> int:
        captured["capture"] = options.capture
        return 0

    monkeypatch.setattr(
        "clawcodex_ext.entrypoints.headless._run_headless_core", _fake_core
    )

    rc = run_headless(HeadlessOptions(prompt="hi", persist_on_exit=False))
    assert rc == 0
    assert captured["capture"] is None
