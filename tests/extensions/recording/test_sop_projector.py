"""Tests for the SOP asciicast projector (F-REC).

The projector has two modes:

* ``capture is None`` — no-op context manager so callers can keep
  the ``with`` block unconditionally without paying any cost
* ``capture`` is set — installs a :class:`TeeWriter` over ``sys.stdout``
  and emits start/done markers around the conversion
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.sop_converter.asciicast_projector import SopStageProjector


def _frames(path: Path) -> list[list[object]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in raw[1:]]


def test_projector_noop_when_capture_is_none() -> None:
    original_stdout = sys.stdout
    with SopStageProjector(None):
        print("ignored line")
    assert sys.stdout is original_stdout


def test_projector_emits_start_and_done_markers(tmp_path: Path) -> None:
    writer = AsciicastWriter(tmp_path / "demo.cast", AsciicastHeader(width=80, height=24))
    writer.open()
    try:
        with SopStageProjector(writer.capture, title="compile SOP"):
            print("hello world")
            projector_holder: dict[str, SopStageProjector] = {}
            with SopStageProjector(writer.capture) as p:
                projector_holder["p"] = p
                p.emit_marker("sop:parse_sdk", text="parse_sdk")
    finally:
        writer.close()

    frames = _frames(tmp_path / "demo.cast")
    markers = [f[2] for f in frames if f[1] == "m"]
    assert markers[0] == "sop:start"
    assert "sop:parse_sdk" in markers
    assert markers[-1] == "sop:done"


def test_projector_tee_writer_captures_print(tmp_path: Path) -> None:
    writer = AsciicastWriter(tmp_path / "demo.cast", AsciicastHeader(width=80, height=24))
    writer.open()
    try:
        with SopStageProjector(writer.capture, title="tee demo"):
            print("captured line 1")
            print("captured line 2")
    finally:
        writer.close()

    frames = _frames(tmp_path / "demo.cast")
    output_frames = [f for f in frames if f[1] == "o"]
    body = "".join(f[2] for f in output_frames)
    assert "captured line 1" in body
    assert "captured line 2" in body


def test_projector_restores_stdout_on_exception(tmp_path: Path) -> None:
    writer = AsciicastWriter(tmp_path / "demo.cast", AsciicastHeader(width=80, height=24))
    writer.open()
    original_stdout = sys.stdout
    try:
        with SopStageProjector(writer.capture):
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                pass
    finally:
        writer.close()

    assert sys.stdout is original_stdout
    frames = _frames(tmp_path / "demo.cast")
    markers = [f[2] for f in frames if f[1] == "m"]
    assert "sop:done" in markers


def test_projector_emits_error_marker_on_exit_exception(tmp_path: Path) -> None:
    writer = AsciicastWriter(tmp_path / "demo.cast", AsciicastHeader(width=80, height=24))
    writer.open()
    try:
        with SopStageProjector(writer.capture):
            raise ValueError("synthetic failure")
    except ValueError:
        pass
    finally:
        writer.close()

    frames = _frames(tmp_path / "demo.cast")
    markers = [f[2] for f in frames if f[1] == "m"]
    assert "sop:error" in markers
    text_frames = [f[2] for f in frames if f[1] == "o"]
    assert any("synthetic failure" in t for t in text_frames)


def test_emit_marker_is_silent_when_capture_is_none() -> None:
    with SopStageProjector(None) as p:
        # Must not raise even with no capture wired.
        p.emit_marker("sop:test")
        p.emit_marker("sop:test", text="ignored")