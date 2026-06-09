"""Tests for parsers: session_parser, transcript_parser, multi_agent_parser, tool_events_parser."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from extensions.visualizer.parsers.session_parser import SessionMetadataParser
from extensions.visualizer.parsers.transcript_parser import TranscriptParser, _coerce_timestamp
from extensions.visualizer.parsers.multi_agent_parser import MultiAgentParser
from extensions.visualizer.parsers.tool_events_parser import ToolEventsParser
from extensions.visualizer.models.viz_models import BarStatus, BarType


# ---------------------------------------------------------------------------
# _coerce_timestamp
# ---------------------------------------------------------------------------


class TestCoerceTimestamp:
    def test_none_returns_zero(self):
        assert _coerce_timestamp(None) == 0.0

    def test_int_returns_float(self):
        assert _coerce_timestamp(1717500000) == 1717500000.0

    def test_float_passthrough(self):
        assert _coerce_timestamp(1717500000.5) == 1717500000.5

    def test_iso8601_string(self):
        # 2024-06-04T12:00:00Z  →  some positive epoch
        ts = _coerce_timestamp("2024-06-04T12:00:00Z")
        assert ts > 0

    def test_iso8601_without_z(self):
        ts = _coerce_timestamp("2024-06-04T12:00:00+00:00")
        assert ts > 0

    def test_unparseable_string_returns_zero(self):
        assert _coerce_timestamp("not-a-date") == 0.0

    def test_empty_string_returns_zero(self):
        assert _coerce_timestamp("") == 0.0

    def test_bool_returns_zero(self):
        # bool is a subclass of int, but we want float conversion
        assert _coerce_timestamp(True) == 1.0
        assert _coerce_timestamp(False) == 0.0


# ---------------------------------------------------------------------------
# TranscriptParser
# ---------------------------------------------------------------------------


class TestTranscriptParser:
    def _make_jsonl(self, tmp: Path, entries: list[dict]) -> Path:
        p = tmp / "transcript.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return p

    def test_parse_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        bars = TranscriptParser().parse_file(p)
        assert bars == []

    def test_parse_nonexistent_file(self):
        bars = TranscriptParser().parse_file(Path("/nonexistent/file.jsonl"))
        assert bars == []

    def test_parse_assistant_text_message(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {"role": "assistant", "content": "Hello, I will help you.", "_timestamp": 1717500000.0},
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.CUSTOM
        assert bars[0].label == "assistant"

    def test_parse_tool_use_block(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "tool_use_id": "tu-1", "input": {"path": "a.py"}},
                ],
                "_timestamp": 1717500000.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].label == "Read"
        assert bars[0].status == BarStatus.RUNNING

    def test_parse_tool_result_block(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "tool_use_id": "tu-1", "input": {}},
                ],
                "_timestamp": 1717500000.0,
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "ok", "is_error": False},
                ],
                "_timestamp": 1717500001.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        # First bar = tool_use, second bar = tool_result
        assert len(bars) == 2
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[1].type == BarType.TOOL_RESULT
        assert bars[1].status == BarStatus.SUCCESS
        assert bars[1].duration_ms == 1000

    def test_parse_tool_result_error(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "tool_use_id": "tu-1", "input": {}},
                ],
                "_timestamp": 1717500000.0,
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-1", "content": "error", "is_error": True},
                ],
                "_timestamp": 1717500002.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert bars[1].status == BarStatus.ERROR

    def test_parse_text_block(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I will now edit the file."},
                ],
                "_timestamp": 1717500000.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL

    def test_skip_system_role(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {"role": "system", "content": "__background_complete__", "_timestamp": 1717500000.0},
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 0

    def test_malformed_json_line_skipped(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not-json\n")
        bars = TranscriptParser().parse_file(p)
        assert bars == []

    def test_parse_incremental(self, tmp_path):
        p = tmp_path / "inc.jsonl"
        p.write_text(json.dumps({"role": "assistant", "content": "hi", "_timestamp": 1.0}) + "\n")
        bars, offset = TranscriptParser().parse_incremental(p, 0)
        assert len(bars) == 1
        assert offset > 0

    def test_parse_incremental_nonexistent(self):
        bars, offset = TranscriptParser().parse_incremental(Path("/nope"), 0)
        assert bars == []
        assert offset == 0

    def test_parse_resets_state_between_files(self, tmp_path):
        """Verify bar counter and pending tools reset on each parse_file call."""
        parser = TranscriptParser()
        p1 = self._make_jsonl(tmp_path, [
            {"role": "assistant", "content": "msg1", "_timestamp": 1.0},
        ])
        p2 = self._make_jsonl(tmp_path, [
            {"role": "assistant", "content": "msg2", "_timestamp": 2.0},
        ])
        bars1 = parser.parse_file(p1)
        bars2 = parser.parse_file(p2)
        # Both should produce a bar with id "msg-1" (counter reset)
        assert bars1[0].id == "msg-1"
        assert bars2[0].id == "msg-1"

    def test_iso8601_timestamp_in_entry(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {"role": "assistant", "content": "hi", "timestamp": "2024-06-04T12:00:00Z"},
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].start_time > 0

    def test_missing_timestamp_uses_last(self, tmp_path):
        p = self._make_jsonl(tmp_path, [
            {"role": "assistant", "content": "first", "_timestamp": 100.0},
            {"role": "assistant", "content": "second"},
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 2
        assert bars[0].start_time == 100.0
        # Second bar inherits the last timestamp
        assert bars[1].start_time == 100.0


# ---------------------------------------------------------------------------
# SessionMetadataParser
# ---------------------------------------------------------------------------


class TestSessionMetadataParser:
    def test_parse_nonexistent_session(self, tmp_path):
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        result = parser.parse("nonexistent-session-id")
        assert result is None

    def test_parse_session_with_metadata(self, tmp_path):
        session_dir = tmp_path / "test-session-001"
        session_dir.mkdir()
        meta = {
            "title": "Test Session",
            "model": "gpt-4",
            "start_time": 1717500000.0,
            "last_updated": 1717500030.0,
            "status": "completed",
            "agent_name": "codex",
            "tags": ["test"],
            "message_count": 5,
            "detected_mode": "headless",
        }
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (session_dir / "transcript.jsonl").write_text("", encoding="utf-8")

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("test-session-001")
        assert viz is not None
        assert viz.session_id == "test-session-001"
        assert viz.title == "Test Session"
        assert viz.model == "gpt-4"
        assert viz.status == "completed"
        assert viz.duration_ms == 30000
        assert viz.turn_count == 5

    def test_parse_session_without_metadata(self, tmp_path):
        session_dir = tmp_path / "minimal-session"
        session_dir.mkdir()
        # No metadata.json, no transcript
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("minimal-session")
        assert viz is not None
        assert viz.status == "unknown"

    def test_list_sessions(self, tmp_path):
        for sid in ["aaa", "bbb", "ccc"]:
            d = tmp_path / sid
            d.mkdir()
            (d / "metadata.json").write_text(json.dumps({"start_time": 1.0}), encoding="utf-8")
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        sessions = parser.list_sessions()
        assert len(sessions) == 3

    def test_list_sessions_limit(self, tmp_path):
        for i in range(5):
            d = tmp_path / f"session-{i}"
            d.mkdir()
            (d / "metadata.json").write_text(json.dumps({"start_time": float(i)}), encoding="utf-8")
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        sessions = parser.list_sessions(limit=2)
        assert len(sessions) == 2


# ---------------------------------------------------------------------------
# ToolEventsParser
# ---------------------------------------------------------------------------


class TestToolEventsParser:
    def test_parse_empty(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text("")
        bars = ToolEventsParser().parse_file(p)
        assert bars == []

    def test_parse_nonexistent(self):
        bars = ToolEventsParser().parse_file(Path("/nope"))
        assert bars == []

    def test_parse_approved_tool(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text(json.dumps({
            "ts": 1717500000.0, "tool": "Bash", "approved": True, "turn": 1,
        }) + "\n")
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].label == "Bash"
        assert bars[0].status == BarStatus.SUCCESS

    def test_parse_denied_tool(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text(json.dumps({
            "ts": 1717500000.0, "tool": "Write", "approved": False, "deny_reason": "permission denied",
        }) + "\n")
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].status == BarStatus.ERROR

    def test_parse_pending_tool(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text(json.dumps({
            "ts": 1717500000.0, "tool": "Read", "approved": None,
        }) + "\n")
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].status == BarStatus.WARNING

    def test_malformed_line_skipped(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text("bad-json\n")
        bars = ToolEventsParser().parse_file(p)
        assert bars == []

    def test_multiple_events(self, tmp_path):
        p = tmp_path / "events.ndjson"
        lines = [
            json.dumps({"ts": 1.0, "tool": "Read", "approved": True}),
            json.dumps({"ts": 2.0, "tool": "Bash", "approved": False, "deny_reason": "no"}),
            json.dumps({"ts": 3.0, "tool": "Write", "approved": True}),
        ]
        p.write_text("\n".join(lines) + "\n")
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 3
        assert bars[0].label == "Read"
        assert bars[1].status == BarStatus.ERROR
        assert bars[2].label == "Write"


# ---------------------------------------------------------------------------
# MultiAgentParser
# ---------------------------------------------------------------------------


class TestMultiAgentParser:
    def test_parse_workspace_no_control_dir(self, tmp_path):
        nodes = MultiAgentParser().parse_workspace(tmp_path, "run-001")
        # Should produce a single root fallback node
        assert len(nodes) == 1
        assert nodes[0].name == "primary-agent"

    def test_parse_workspace_with_agent_meta(self, tmp_path):
        control_dir = tmp_path / ".orchestrator_control" / "runs" / "run-001"
        control_dir.mkdir(parents=True)
        meta = {
            "agents": [
                {"id": "agent-1", "name": "coordinator", "status": "success", "parent_id": None},
                {"id": "agent-2", "name": "worker-1", "status": "running", "parent_id": "agent-1"},
            ]
        }
        (control_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        nodes = MultiAgentParser().parse_workspace(tmp_path, "run-001")
        assert len(nodes) == 2
        assert nodes[0].agent_id == "agent-1"
        assert nodes[1].parent_id == "agent-1"

    def test_parse_workspace_invalid_meta(self, tmp_path):
        control_dir = tmp_path / ".orchestrator_control" / "runs" / "run-002"
        control_dir.mkdir(parents=True)
        (control_dir / "agent_meta.json").write_text("not-valid-json", encoding="utf-8")
        nodes = MultiAgentParser().parse_workspace(tmp_path, "run-002")
        # Falls back to single root
        assert len(nodes) == 1
