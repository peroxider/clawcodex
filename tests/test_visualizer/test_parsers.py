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

    def test_tool_call_duration_backfilled_from_result(self, tmp_path):
        """After parse_file, the TOOL_CALL bar's duration_ms is backfilled
        from the matching TOOL_RESULT. Without this, stats like
        Avg Duration include the 0-duration TOOL_CALL placeholders and
        come out artificially low (the bug fixed by F-97 / transcript_parser
        _pair_tool_durations)."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "tool_use_id": "tu-a", "input": {}},
                ],
                "_timestamp": 1717500000.0,
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-a", "content": "ok", "is_error": False},
                ],
                "_timestamp": 1717500001.5,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 2
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].duration_ms == 1500  # 1.5s
        assert bars[0].end_time == 1717500001.5
        assert bars[1].duration_ms == 1500  # tool_result kept its own duration

    def test_tool_call_duration_stays_zero_without_result(self, tmp_path):
        """A TOOL_CALL with no matching TOOL_RESULT AND no following bar
        keeps duration_ms=0 — there's no signal to estimate from, so the
        bar is correctly left as a still-running placeholder. (A next
        bar IS the signal; covered by
        ``test_tool_call_duration_estimated_from_next_bar`` below.)"""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "tool_use_id": "tu-x", "input": {}},
                ],
                "_timestamp": 1717500000.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].duration_ms == 0

    def test_tool_call_duration_estimated_from_next_bar(self, tmp_path):
        """A TOOL_CALL with no matching TOOL_RESULT but with a following
        bar in the timeline gets its duration estimated from the next
        bar's start_time. This is the case the F-97 follow-up caught
        in the wild — sessions killed mid-tool leave tool_use blocks
        with no tool_result. The next bar's start_time is a reasonable
        upper bound on the actual tool latency."""
        p = self._make_jsonl(tmp_path, [
            # Agent tool_use at t=100, next bar at t=130 → 30s estimate
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Agent", "id": "call_a", "input": {}},
                ],
                "_timestamp": 100.0,
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Agent", "id": "call_b", "input": {}},
                ],
                "_timestamp": 130.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 2
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].duration_ms == 30000  # 30s
        assert bars[0].end_time == 130.0
        assert bars[1].duration_ms == 0  # no next bar; stays as placeholder

    def test_tool_call_fallback_with_only_text_after(self, tmp_path):
        """A TOOL_CALL followed by a text block (typical end-of-turn
        pattern) gets the estimate from the text block's start_time."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "id": "call_x", "input": {}},
                ],
                "_timestamp": 200.0,
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done."}],
                "_timestamp": 200.5,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 2
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].duration_ms == 500
        assert bars[0].end_time == 200.5

    def test_entry_with_multiple_blocks_emits_one_bar_per_block(self, tmp_path):
        """A single transcript entry can carry multiple content blocks
        (Anthropic API format: ``[text, tool_use, tool_use, ...]``).
        The parser must emit one bar per non-empty block — the earlier
        "first bar per entry" simplification dropped the rest, which
        hid parallel tool_use calls from the gantt and biased Avg
        Duration stats."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me look at a few files."},
                    {"type": "tool_use", "name": "Read", "id": "c1", "input": {}},
                    {"type": "tool_use", "name": "Read", "id": "c2", "input": {}},
                    {"type": "tool_use", "name": "Read", "id": "c3", "input": {}},
                ],
                "_timestamp": 100.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        # 1 text + 3 tool_use = 4 bars, not 1
        assert len(bars) == 4
        assert bars[0].type == BarType.LLM_CALL
        assert bars[1].type == BarType.TOOL_CALL
        assert bars[2].type == BarType.TOOL_CALL
        assert bars[3].type == BarType.TOOL_CALL
        # All three Reads have distinct IDs (counter increments per block)
        ids = [b.id for b in bars[1:]]
        assert len(set(ids)) == 3, f"expected 3 distinct bar ids, got {ids}"

    def test_single_text_only_entry_unchanged(self, tmp_path):
        """Regression guard: an entry with a single text block must still
        produce exactly one bar (the "all blocks per entry" fix should
        not turn a single text bar into 0 or 2+ bars)."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Just a single text block."},
                ],
                "_timestamp": 50.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL

    def test_entry_with_empty_content_blocks_skips_them(self, tmp_path):
        """An entry whose content list contains blocks that yield no
        bar (e.g. text with empty string, tool_use with missing name)
        must not produce phantom bars. Specifically: empty text is
        dropped by _text_bar(); only the surviving non-empty blocks
        appear in the output."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": ""},  # dropped
                    {"type": "tool_use", "name": "Read", "id": "keep", "input": {}},
                ],
                "_timestamp": 60.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        # Only the Read survives the empty-text drop
        assert len(bars) == 1
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].label == "Read"

    def test_real_session_pattern_no_tool_results(self, tmp_path):
        """Mirrors the real production session pattern that triggered
        this fix: 10 tool_use blocks spread across multiple entries
        (some parallel in the same entry), 0 tool_result blocks
        (the session was killed before any result came back, or the
        upstream writer only emits tool_use events).

        Expectations after the "all blocks per entry" fix:
          - entry 1 (user msg): 1 bar
          - entry 2 (text + Agent): 2 bars
          - entry 3 (Agent): 1 bar
          - entry 4 (Agent): 1 bar
          - entry 5 (text + 3 Reads): 4 bars
          - entry 6 (2 Reads): 2 bars
          → 11 total bars, 8 tool_call bars.

        Every tool_call bar that has a strictly-later bar in the
        timeline (i.e. not the last parallel sibling) gets a non-zero
        duration estimated from that next bar. The last two Reads
        in entry 6 are the only tool_calls with no strictly-later
        signal, so they correctly stay at 0 — they're the real last
        bars of the session."""
        p = self._make_jsonl(tmp_path, [
            # entry 1: user message
            {"role": "user", "content": "请分析 tab 补全", "timestamp": 1000.0},
            # entry 2: assistant [text, tool_use Agent]  → all blocks kept
            {"role": "assistant",
             "content": [
                 {"type": "text", "text": "I'll explore."},
                 {"type": "tool_use", "name": "Agent", "id": "call_01", "input": {}},
             ],
             "timestamp": 1010.0},
            # entry 3: tool_use Agent
            {"role": "assistant",
             "content": [{"type": "tool_use", "name": "Agent", "id": "call_02", "input": {}}],
             "timestamp": 1030.0},
            # entry 4: tool_use Agent
            {"role": "assistant",
             "content": [{"type": "tool_use", "name": "Agent", "id": "call_03", "input": {}}],
             "timestamp": 1045.0},
            # entry 5: [text, Read, Read, Read] → all 4 blocks kept
            {"role": "assistant",
             "content": [
                 {"type": "text", "text": "Looking deeper..."},
                 {"type": "tool_use", "name": "Read", "id": "call_04", "input": {}},
                 {"type": "tool_use", "name": "Read", "id": "call_05", "input": {}},
                 {"type": "tool_use", "name": "Read", "id": "call_06", "input": {}},
             ],
             "timestamp": 1100.0},
            # entry 6: [Read, Read] → both kept, parallel siblings
            {"role": "assistant",
             "content": [
                 {"type": "tool_use", "name": "Read", "id": "call_07", "input": {}},
                 {"type": "tool_use", "name": "Read", "id": "call_08", "input": {}},
             ],
             "timestamp": 1105.0},
        ])
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 11

        tool_calls = [b for b in bars if b.type == BarType.TOOL_CALL]
        # 8 tool_call bars: 1 + 1 + 1 + 3 + 2
        assert len(tool_calls) == 8
        # All tool_call bars that have a strictly-later neighbor in
        # the timeline get a non-zero estimate; only the last two
        # parallel Reads in entry 6 have no strictly-later bar, so
        # they stay at 0 (correctly — they're the real end of the
        # session).
        non_zero = [tc for tc in tool_calls if tc.duration_ms > 0]
        zero = [tc for tc in tool_calls if tc.duration_ms == 0]
        assert len(non_zero) == 6
        assert len(zero) == 2
        # Spot-check estimates:
        #   entry 2 Agent (t=1010) → next bar entry 3 Agent (t=1030) = 20s
        assert tool_calls[0].duration_ms == 20000
        #   entry 3 Agent (t=1030) → entry 4 Agent (t=1045) = 15s
        assert tool_calls[1].duration_ms == 15000
        #   entry 4 Agent (t=1045) → entry 5 text (t=1100) = 55s
        assert tool_calls[2].duration_ms == 55000
        #   entry 5 Reads (parallel, t=1100) all skip their siblings
        #   and the entry 5 text bar, landing on entry 6 Reads (t=1105) = 5s
        for tc in tool_calls[3:6]:
            assert tc.duration_ms == 5000, (
                f"parallel Read {tc.id} expected 5000ms, got {tc.duration_ms}"
            )
        #   entry 6 Reads (parallel, t=1105) have no strictly-later bar
        for tc in tool_calls[6:8]:
            assert tc.duration_ms == 0, (
                f"trailing Read {tc.id} expected 0ms (no later bar), "
                f"got {tc.duration_ms}"
            )

    def test_orphan_tool_result_does_not_modify_other_calls(self, tmp_path):
        """A TOOL_RESULT whose tool_use_id has no matching TOOL_CALL
        must not backfill anything (e.g. a replay that starts mid-stream)."""
        p = self._make_jsonl(tmp_path, [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "tool_use_id": "tu-a", "input": {}},
                ],
                "_timestamp": 1717500000.0,
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu-orphan", "content": "ok"},
                ],
                "_timestamp": 1717500001.0,
            },
        ])
        bars = TranscriptParser().parse_file(p)
        # TOOL_CALL bar (no result) is left at duration 0
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].duration_ms == 0
        # Orphan TOOL_RESULT exists as its own bar — start_time=ts=end_time
        # in _tool_result_bar (no pending tool_use), so duration is 0 by
        # design. Critically it does NOT backfill the unrelated tu-a bar.
        assert bars[1].type == BarType.TOOL_RESULT
        assert bars[1].duration_ms == 0
        assert bars[0].end_time == 1717500000.0  # not overwritten by orphan

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

    # ---- _infer_status recency behavior (drives live polling) ----

    def test_status_recent_transcript_is_running(self, tmp_path):
        """A session whose transcript was touched <5 min ago is 'running'."""
        import time as _time
        session_dir = tmp_path / "live-session"
        session_dir.mkdir()
        meta = {"start_time": _time.time() - 60, "last_updated": _time.time() - 60}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text('{"role":"assistant","content":[]}\n', encoding="utf-8")
        # mtime is "now" because we just wrote the file.

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("live-session")
        assert viz is not None
        assert viz.status == "running"

    def test_status_recent_last_updated_is_running(self, tmp_path):
        """A session whose last_updated is recent is 'running' even if
        the transcript mtime is stale (e.g. metadata is being kept fresh
        by the agent loop while no new tool calls happen)."""
        import time as _time
        session_dir = tmp_path / "live-session"
        session_dir.mkdir()
        meta = {"start_time": _time.time() - 600, "last_updated": _time.time() - 30}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        # Old transcript mtime (10 min ago) — beyond the 5-min window.
        old = _time.time() - 600
        tp = session_dir / "transcript.jsonl"
        tp.write_text('{"role":"assistant","content":[]}\n', encoding="utf-8")
        import os
        os.utime(tp, (old, old))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("live-session")
        assert viz is not None
        assert viz.status == "running"

    def test_status_old_transcript_is_completed(self, tmp_path):
        """A session whose transcript is older than 5 min is 'completed'."""
        import os
        import time as _time
        session_dir = tmp_path / "old-session"
        session_dir.mkdir()
        old = _time.time() - 3600
        meta = {"start_time": old - 60, "last_updated": old}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text('{"role":"assistant","content":[]}\n', encoding="utf-8")
        os.utime(tp, (old, old))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("old-session")
        assert viz is not None
        assert viz.status == "completed"

    def test_status_explicit_wins_over_recency(self, tmp_path):
        """An explicit 'status' in metadata is always respected, even if
        the transcript mtime is fresh — handles the case where the agent
        loop writes status='completed' before flushing the transcript."""
        import time as _time
        session_dir = tmp_path / "weird-session"
        session_dir.mkdir()
        meta = {
            "start_time": _time.time() - 60,
            "last_updated": _time.time() - 5,
            "status": "failed",
        }
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text('{"role":"assistant","content":[]}\n', encoding="utf-8")

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("weird-session")
        assert viz is not None
        assert viz.status == "failed"

    def test_status_no_transcript_no_metadata_is_unknown(self, tmp_path):
        session_dir = tmp_path / "bare-session"
        session_dir.mkdir()
        # No metadata.json, no transcript.jsonl
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("bare-session")
        assert viz is not None
        assert viz.status == "unknown"

    def test_status_stale_short_session_is_completed(self, tmp_path):
        """Regression: a session that ran for <5s and was killed 47h ago
        (e.g. 429 rate limit 27ms after start) must NOT be reported as
        ``"running"``. The old ``last < start + 5`` fallback returned
        ``"running"`` for any short session regardless of age, which
        stuck stale orchestrator failures as "running" forever.
        Reproduces the ``run-01-20260608T085433Z`` mis-classification
        (orchestrator-ISSUE-429, killed by 429 in 27ms)."""
        import os
        import time as _time
        session_dir = tmp_path / "stale-short"
        session_dir.mkdir()
        # 47 hours ago, ran for 27ms, then died.
        ancient = _time.time() - 47 * 3600
        meta = {"start_time": ancient, "last_updated": ancient + 0.027}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text('{"role":"assistant","content":[]}\n', encoding="utf-8")
        # mtime matches last_updated — transcript is also 47h stale.
        os.utime(tp, (ancient, ancient))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("stale-short")
        assert viz is not None
        # Both signals are >47h old, so neither rule 2 (mtime <5min)
        # nor rule 3 (last_updated <5min) fires. The session is stale.
        # The old code returned "running" here via the brand-new
        # fallback; the fix returns "completed".
        assert viz.status == "completed", (
            f"stale short session mis-classified as {viz.status!r} "
            f"(expected 'completed')"
        )


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
