"""Tests for the orchestrator asciicast sink (F-REC).

Covers the mapping from :class:`ProgressSink` callbacks into
:class:`AsciicastCapture` markers:

* ``on_phase_complete`` → ``[phase N/T]`` marker + matching text line
* ``on_turn_complete``   → debug log only (no capture frame; matches
  the live console's noise policy)
* ``on_session_complete``→ ``session:<reason>`` marker + summary text
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from extensions.api.query import (
    PhaseComplete,
    SessionComplete,
    TurnComplete,
)
from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.orchestrator.asciicast_sink import (
    AsciicastSink,
    format_phase_label,
)


class _FakeSession:
    """Minimal stand-in for the AgentSession interface the sink touches."""

    def __init__(self, task_id: str = "issue-42") -> None:
        self.task_id = task_id


def _open_writer(tmp_path: Path) -> AsciicastWriter:
    writer = AsciicastWriter(
        tmp_path / "demo.cast",
        AsciicastHeader(width=120, height=36),
    )
    writer.open()
    return writer


def _frames(path: Path) -> list[list[Any]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in raw[1:]]


def test_phase_marker_uses_total_when_known(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="issue-1", phases_total=5)
    sink.on_phase_complete(PhaseComplete(phase=3, turn_count=12), _FakeSession())
    writer.close()

    frames = _frames(tmp_path / "demo.cast")
    assert [f[1] for f in frames] == ["m", "o"]
    assert frames[0][2] == "[phase 3/5]"
    assert frames[1][2] == "[phase 3/5]"


def test_phase_marker_omits_total_when_unknown(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="issue-1")
    sink.on_phase_complete(PhaseComplete(phase=2, turn_count=8), _FakeSession())
    writer.close()

    frames = _frames(tmp_path / "demo.cast")
    assert frames[0][2] == "[phase 2]"


def test_turn_complete_is_silent_in_capture(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="issue-1")
    sink.on_turn_complete(TurnComplete(turn=7), _FakeSession())
    writer.close()
    # No frame written — only the header line is in the file.
    raw = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1
    header = json.loads(raw[0])
    assert header["version"] == 2
    assert header["width"] == 120
    assert header["height"] == 36


def test_session_complete_emits_session_marker(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="issue-7")
    sink.on_session_complete(SessionComplete(reason="exit_code=0"), _FakeSession())
    writer.close()

    frames = _frames(tmp_path / "demo.cast")
    assert frames[0][1] == "m"
    assert frames[0][2] == "session:exit_code=0"
    assert frames[1][1] == "o"
    assert "issue-7" in frames[1][2]
    assert "exit_code=0" in frames[1][2]


def test_session_complete_without_task_id_still_works(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="")
    sink.on_session_complete(SessionComplete(reason="cancelled"), _FakeSession())
    writer.close()

    frames = _frames(tmp_path / "demo.cast")
    assert "cancelled" in frames[1][2]
    assert "ended:" in frames[1][2]


def test_sink_keeps_going_when_capture_is_closed(tmp_path: Path) -> None:
    """Capture failure must never crash the orchestrator."""
    writer = _open_writer(tmp_path)
    sink = AsciicastSink(writer.capture, task_id="issue-1", phases_total=3)
    writer.close()
    # Should log and move on rather than raising.
    sink.on_phase_complete(PhaseComplete(phase=1, turn_count=4), _FakeSession())
    sink.on_session_complete(SessionComplete(reason="exit_code=1"), _FakeSession())


def test_format_phase_label_helper() -> None:
    assert format_phase_label(3, 7) == "[phase 3/7]"
    assert format_phase_label(3, None) == "[phase 3]"
    assert format_phase_label(0, 4) == "[phase 0/4]"