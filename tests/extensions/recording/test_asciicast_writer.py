"""Tests for the asciicast v2 writer (F-REC).

Covers the wire format guarantees the rest of the recorder relies on:

* header line 1 is JSON with ``version: 2`` and required width/height
* every frame is a 3-element JSON array ``[t, kind, data]``
* frames are flushed per frame (so a reader tailing the file sees
  events as they happen)
* concurrent emits from multiple threads keep monotonic ordering
* ANSI escapes round-trip verbatim inside the ``data`` field
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from extensions.capabilities.recorder import (
    AsciicastEvent,
    AsciicastHeader,
)
from extensions.recording.asciicast_writer import AsciicastWriter


def _open_writer(tmp_path: Path, **header_kwargs: object) -> AsciicastWriter:
    header = AsciicastHeader(
        width=int(header_kwargs.get("width", 120)),
        height=int(header_kwargs.get("height", 36)),
        timestamp=int(header_kwargs.get("timestamp", 0)) or None,
        title=header_kwargs.get("title") if "title" in header_kwargs else None,
    )
    return AsciicastWriter(tmp_path / "demo.cast", header)


def test_writer_writes_v2_header_with_required_fields(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path, title="hello")
    with writer as capture:
        capture.marker("start")

    lines = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    assert header["version"] == 2
    assert header["width"] == 120
    assert header["height"] == 36
    assert header["title"] == "hello"
    assert "command" not in header  # unset fields stay out


def test_writer_emits_marker_as_m_frame(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    with writer as capture:
        capture.marker("phase:1")

    lines = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # header + 1 marker
    event = json.loads(lines[1])
    assert len(event) == 3
    assert event[1] == "m"
    assert event[2] == "phase:1"
    assert isinstance(event[0], (int, float))
    assert event[0] >= 0


def test_writer_marker_with_text_emits_two_frames(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    with writer as capture:
        capture.marker("phase:1", text="started phase 1")

    lines = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # header + m + o
    assert json.loads(lines[1])[1] == "m"
    assert json.loads(lines[2])[1] == "o"
    assert json.loads(lines[2])[2] == "started phase 1"


def test_writer_emit_records_o_i_r_frames(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    with writer as capture:
        capture.emit(AsciicastEvent(t=0.1, kind="o", data="hello"))
        capture.emit(AsciicastEvent(t=0.2, kind="i", data="x"))
        capture.resize(80, 24)

    lines = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    codes = [json.loads(line)[1] for line in lines[1:]]
    assert codes == ["o", "i", "r"]
    assert json.loads(lines[3])[2] == "80x24"


def test_writer_preserves_ansi_escapes_verbatim(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    payload = "\x1b[31mred\x1b[0m \x1b[1mbold\x1b[0m"
    with writer as capture:
        capture.emit(AsciicastEvent(t=0.1, kind="o", data=payload))

    lines = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[1])
    assert event[2] == payload


def test_writer_escapes_u2028_u2029_in_data(tmp_path: Path) -> None:
    """U+2028 / U+2029 are valid JSON but break NDJSON receivers."""
    writer = _open_writer(tmp_path)
    payload = "line\u2028break\u2029end"
    with writer as capture:
        capture.emit(AsciicastEvent(t=0.1, kind="o", data=payload))

    raw = (tmp_path / "demo.cast").read_text(encoding="utf-8")
    # The bare line separators must not survive into the .cast file
    # (they'd be split into multiple JSONL lines by naive consumers).
    assert "\u2028" not in raw
    assert "\u2029" not in raw
    # ...but the round-tripped payload still contains them.
    event = json.loads(raw.splitlines()[1])
    assert event[2] == payload


def test_writer_per_frame_flush(tmp_path: Path) -> None:
    """A reader that opens the file mid-run should see partial output.

    The writer flushes after every frame (per the F-REC plan) so
    ``tail -f`` works and CI can inspect in-progress captures.
    """
    writer = _open_writer(tmp_path)
    capture = writer.open()
    try:
        capture.marker("frame-1")
        # File must be readable and contain the first marker right now.
        snapshot = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
        assert len(snapshot) == 2
        assert json.loads(snapshot[1])[2] == "frame-1"

        capture.marker("frame-2")
        snapshot = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
        assert len(snapshot) == 3
    finally:
        writer.close()


def test_writer_close_is_idempotent(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    writer.open()
    writer.close()
    writer.close()  # second call must not raise


def test_writer_drop_frame_after_close(tmp_path: Path) -> None:
    """Captures are closed mid-emit by the source tear-down path —
    the writer must drop frames silently rather than crashing."""
    writer = _open_writer(tmp_path)
    capture = writer.open()
    writer.close()
    # Should be a no-op, not an exception.
    capture.marker("after-close")
    capture.emit(AsciicastEvent(t=1.0, kind="o", data="late"))
    assert writer.frame_count == 0


def test_writer_concurrent_emits_keep_monotonic_order(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    threads_n = 4
    frames_per_thread = 200
    capture = writer.open()

    def _emit(thread_id: int) -> None:
        for i in range(frames_per_thread):
            capture.emit(
                AsciicastEvent(
                    t=i,
                    kind="o",
                    data=f"t{thread_id}-f{i}",
                )
            )

    threads = [
        threading.Thread(target=_emit, args=(i,)) for i in range(threads_n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    writer.close()

    raw = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1 + threads_n * frames_per_thread
    # Per-thread ordering is preserved (the writer never re-orders
    # frames from the same thread; only inter-thread interleaving is
    # non-deterministic, which is correct under concurrent emit).
    by_thread: dict[str, list[int]] = {}
    for line in raw[1:]:
        payload = json.loads(line)[2]
        thread_id, _, idx = payload.partition("-f")
        by_thread.setdefault(thread_id, []).append(int(idx))
    for thread_id, indices in by_thread.items():
        assert indices == sorted(indices), f"thread {thread_id} frames out of order"
    # No drops / no duplicates.
    payloads = [json.loads(line)[2] for line in raw[1:]]
    assert sorted(payloads) == sorted(
        f"t{thread_id}-f{i}"
        for thread_id in range(threads_n)
        for i in range(frames_per_thread)
    )


def test_writer_header_timestamps_default_to_none(tmp_path: Path) -> None:
    """``timestamp=None`` means *omitted from the encoded header*."""
    writer = AsciicastWriter(
        tmp_path / "demo.cast",
        AsciicastHeader(width=80, height=24),
    )
    with writer:
        pass
    header = json.loads((tmp_path / "demo.cast").read_text().splitlines()[0])
    assert "timestamp" not in header
    assert "idle_time_limit" not in header
    assert "env" not in header