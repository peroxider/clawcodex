"""Tests for the visualizer asciicast dashboard source (F-REC)."""

from __future__ import annotations

import json
from pathlib import Path

from extensions.capabilities.dashboard_entry import (
    DASHBOARD_STATUS_COMPLETED,
    DASHBOARD_STATUS_FAILED,
    DASHBOARD_STATUS_IN_PROGRESS,
    DASHBOARD_STATUS_PENDING,
    DashboardEntry,
)
from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.visualizer.asciicast_dashboard_source import (
    AsciicastDashboardSource,
)


def _open_writer(tmp_path: Path) -> AsciicastWriter:
    writer = AsciicastWriter(
        tmp_path / "demo.cast",
        AsciicastHeader(width=120, height=36),
    )
    writer.open()
    return writer


def _body_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in raw[1:]:
        event = json.loads(line)
        if event[1] == "o":
            out.append(event[2])
    return "".join(out)


def test_source_has_dashboard_protocol_basics() -> None:
    src = AsciicastDashboardSource()
    assert src.source_name == "visualizer_asciicast"
    assert src.cache_ttl_ms == 1000
    # The recording-only source returns an empty pull — its value is in
    # record_snapshot, not in the live pull path.
    assert src.pull() == []


def test_record_snapshot_emits_marker_and_panels(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    src = AsciicastDashboardSource()
    entries = [
        DashboardEntry(
            id="orch-1",
            source="orchestrator",
            title="fix bug",
            status=DASHBOARD_STATUS_IN_PROGRESS,
            progress_pct=0.4,
        ),
        DashboardEntry(
            id="orch-2",
            source="orchestrator",
            title="ship feature",
            status=DASHBOARD_STATUS_COMPLETED,
            progress_pct=1.0,
        ),
    ]
    src.record_snapshot(writer.capture, entries, title="Demo Run")
    writer.close()

    body = _body_text(tmp_path / "demo.cast")
    # Stats line shows all four status buckets.
    assert "⏳ pending" in body
    assert "🔵 running" in body
    assert "✅ done" in body
    assert "❌ failed" in body
    # Each non-empty group gets its own detail panel.
    assert "orch-1" in body
    assert "orch-2" in body
    assert "fix bug" in body
    assert "ship feature" in body
    # Progress percent is rendered.
    assert "40%" in body
    assert "100%" in body


def test_record_snapshot_handles_empty_entries(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    src = AsciicastDashboardSource()
    src.record_snapshot(writer.capture, [], title="Empty")
    writer.close()

    body = _body_text(tmp_path / "demo.cast")
    assert "Empty" in body
    assert "(no entries)" in body


def test_record_snapshot_caps_rows_per_group(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    src = AsciicastDashboardSource()
    entries = [
        DashboardEntry(
            id=f"e-{i}",
            source="orchestrator",
            title=f"task {i}",
            status=DASHBOARD_STATUS_PENDING,
        )
        for i in range(20)
    ]
    src.record_snapshot(writer.capture, entries, title="Big")
    writer.close()

    body = _body_text(tmp_path / "demo.cast")
    # 8 entries shown plus "… and 12 more".
    assert "… and 12 more" in body


def test_record_snapshot_groups_unknown_status_as_pending(tmp_path: Path) -> None:
    """An entry with an off-spec status still renders, bucketed as pending."""
    writer = _open_writer(tmp_path)
    src = AsciicastDashboardSource()
    entries = [
        DashboardEntry(
            id="weird",
            source="orchestrator",
            title="off-spec",
            status="unknown-status",
        )
    ]
    src.record_snapshot(writer.capture, entries, title="Quirk")
    writer.close()

    body = _body_text(tmp_path / "demo.cast")
    assert "weird" in body
    assert "off-spec" in body