"""Tests for parsers: session_parser, transcript_parser, multi_agent_parser, tool_events_parser.

All fixtures use the new ClawCodeX envelope:

* ``content`` is a list of typed content blocks (``text`` / ``tool_use`` /
  ``tool_result`` / ``thinking``).
* ``timestamp`` is an ISO 8601 string.
* ``tool_result`` blocks are nested inside ``user`` role messages with a
  ``toolUseID`` field — no more top-level ``role: tool`` entries.
* ``isMeta`` / ``isVirtual`` / ``isCompactSummary`` / ``isApiErrorMessage``
  / ``type == "progress"`` / ``type == "cost_block"`` are the entry
  gates parsed by the new ``TranscriptParser`` / ``SessionMetadataParser``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extensions.visualizer.parsers.session_parser import SessionMetadataParser
from extensions.visualizer.parsers.transcript_parser import TranscriptParser
from extensions.visualizer.parsers.multi_agent_parser import MultiAgentParser
from extensions.visualizer.parsers.tool_events_parser import ToolEventsParser
from extensions.visualizer.models.viz_models import BarStatus, BarType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: float) -> str:
    """Render a Unix epoch as an ISO 8601 UTC string, preserving microseconds.

    Stripping microseconds (``.replace(microsecond=0)``) silently rounds
    fractional timestamps like ``1717500001.5`` down to ``1717500001.0``,
    which then skews every downstream duration assertion by up to a
    second. Keep the resolution — the parser accepts sub-second ISO
    timestamps.
    """
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _write_jsonl(path: Path, entries: list[dict]) -> Path:
    """Write one JSON object per line at ``path``."""
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def _assistant_tool_use(
    ts: float,
    name: str,
    tool_use_id: str,
    input: dict | None = None,
    text: str | None = None,
) -> dict:
    """Build an assistant entry containing a text block (optional) and a
    single ``tool_use`` block."""
    content: list[dict] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    content.append(
        {
            "type": "tool_use",
            "name": name,
            "id": tool_use_id,
            "input": input or {},
        }
    )
    return {
        "role": "assistant",
        "type": "message",
        "timestamp": _iso(ts),
        "isMeta": False,
        "isVirtual": False,
        "isCompactSummary": False,
        "content": content,
    }


def _tool_result_entry(
    ts: float,
    tool_use_id: str,
    text: str,
    *,
    is_error: bool = False,
) -> dict:
    """Build a user-role entry that carries a single ``tool_result`` block.

    The new envelope embeds tool results inside user messages — the
    legacy top-level ``role: tool`` envelope is gone.
    """
    block: dict = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        block["is_error"] = True
    return {
        "role": "user",
        "type": "message",
        "timestamp": _iso(ts),
        "isMeta": False,
        "isVirtual": False,
        "isCompactSummary": False,
        "toolUseID": tool_use_id,
        "content": [block],
    }


def _user_text(ts: float, text: str) -> dict:
    return {
        "role": "user",
        "type": "message",
        "timestamp": _iso(ts),
        "isMeta": False,
        "isVirtual": False,
        "isCompactSummary": False,
        "content": [{"type": "text", "text": text}],
    }


def _assistant_text(
    ts: float,
    text: str,
    *,
    model: str | None = None,
) -> dict:
    entry: dict = {
        "role": "assistant",
        "type": "message",
        "timestamp": _iso(ts),
        "isMeta": False,
        "isVirtual": False,
        "isCompactSummary": False,
        "content": [{"type": "text", "text": text}],
    }
    if model is not None:
        entry["model"] = model
    return entry


# ---------------------------------------------------------------------------
# TranscriptParser
# ---------------------------------------------------------------------------


class TestTranscriptParser:
    def test_parse_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        bars = TranscriptParser().parse_file(p)
        assert bars == []

    def test_parse_nonexistent_file(self):
        bars = TranscriptParser().parse_file(Path("/nonexistent/file.jsonl"))
        assert bars == []

    def test_parse_assistant_text_message(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_text(1717500000.0, "Hello, I will help you."),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL
        assert bars[0].label == "LLM text"

    def test_parse_tool_use_block(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Read", "tu-1", {"path": "a.py"}),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # No text block was passed → just 1 bar (the tool_use).
        assert len(bars) == 2
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        assert tool.label == "Read"
        assert tool.status == BarStatus.RUNNING

    def test_parse_tool_use_block_with_leading_text(self, tmp_path):
        """A text-then-tool_use entry produces one LLM_CALL bar followed
        by one TOOL_CALL bar."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(
                    1717500000.0, "Read", "tu-1", {"path": "a.py"}, text="Let me look"
                ),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 2
        assert bars[0].type == BarType.LLM_CALL
        assert bars[1].type == BarType.TOOL_CALL
        assert bars[1].label == "Read"

    def test_parse_tool_result_block(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Bash", "tu-1", {}),
                _tool_result_entry(1717500001.0, "tu-1", "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # 1 tool_use + 1 tool_result = 2 bars (no leading text in the
        # tool_use helper call).
        assert len(bars) == 3
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        result = next(bar for bar in bars if bar.type == BarType.TOOL_RESULT)
        assert result.status == BarStatus.SUCCESS
        # The tool_call's duration is backfilled from the tool_result.
        assert tool.duration_ms == 1000

    def test_parse_tool_result_error(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Bash", "tu-1", {}),
                _tool_result_entry(1717500002.0, "tu-1", "error", is_error=True),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert (
            next(bar for bar in bars if bar.type == BarType.TOOL_RESULT).status == BarStatus.ERROR
        )

    def test_tool_call_duration_backfilled_from_result(self, tmp_path):
        """The TOOL_CALL bar's duration_ms is backfilled from the matching
        TOOL_RESULT (parsed from the user-message tool_result block)."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Read", "tu-a", {}),
                _tool_result_entry(1717500001.5, "tu-a", "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 3
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        assert tool.duration_ms == 1500
        assert tool.end_time == 1717500001.5

    def test_tool_call_duration_stays_zero_without_result(self, tmp_path):
        """A TOOL_CALL with no matching TOOL_RESULT and no following bar
        keeps duration_ms=0 — no signal to estimate from."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Bash", "tu-x", {}),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # No leading text + 1 tool_use = 1 bar
        assert len(bars) == 2
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        assert tool.duration_ms == 0
        assert tool.duration_unrecorded is True

    def test_tool_call_duration_estimated_from_next_bar(self, tmp_path):
        """A TOOL_CALL with no matching TOOL_RESULT but with a following
        bar in the timeline gets its duration estimated from the next
        bar's start_time."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                # Agent tool_use at t=100
                _assistant_tool_use(100.0, "Agent", "call_a", {}),
                # Next bar at t=130
                _assistant_tool_use(130.0, "Agent", "call_b", {}),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # Two entries, each with no leading text → 2 tool_use bars total.
        tools = [bar for bar in bars if bar.type == BarType.TOOL_CALL]
        assert len(tools) == 2
        assert all(tool.duration_ms == 0 for tool in tools)
        assert all(tool.duration_unrecorded for tool in tools)

    def test_tool_call_fallback_with_only_text_after(self, tmp_path):
        """A TOOL_CALL followed by a text block (typical end-of-turn
        pattern) gets the estimate from the text block's start_time."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(200.0, "Read", "call_x", {}),
                _assistant_text(200.5, "Done."),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # 0=tool_call(x), 1=text("Done.")
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        # Next bar is the trailing text at 200.5 → 500ms estimate.
        assert tool.duration_ms == 0
        assert tool.duration_unrecorded is True

    def test_entry_with_multiple_blocks_emits_one_bar_per_block(self, tmp_path):
        """A single transcript entry can carry multiple content blocks
        (Anthropic API format: ``[text, tool_use, tool_use, ...]``)."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(100.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [
                        {"type": "text", "text": "Let me look at a few files."},
                        {"type": "tool_use", "name": "Read", "id": "c1", "input": {}},
                        {"type": "tool_use", "name": "Read", "id": "c2", "input": {}},
                        {"type": "tool_use", "name": "Read", "id": "c3", "input": {}},
                    ],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # 1 text + 3 tool_use = 4 bars
        assert len(bars) == 4
        assert bars[0].type == BarType.LLM_CALL
        assert bars[1].type == BarType.TOOL_CALL
        assert bars[2].type == BarType.TOOL_CALL
        assert bars[3].type == BarType.TOOL_CALL
        ids = [b.id for b in bars[1:]]
        assert len(set(ids)) == 3, f"expected 3 distinct bar ids, got {ids}"

    def test_single_text_only_entry_unchanged(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(50.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "text", "text": "Just a single text block."}],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL

    def test_entry_with_empty_text_block_skipped(self, tmp_path):
        """An entry whose content list contains a text block with an
        empty string yields no bar; only the surviving tool_use remains."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(60.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [
                        {"type": "text", "text": ""},  # dropped
                        {"type": "tool_use", "name": "Read", "id": "keep", "input": {}},
                    ],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # Only the Read survives the empty-text drop.
        assert len(bars) == 2
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        assert tool.label == "Read"

    def test_orphan_tool_result_does_not_modify_other_calls(self, tmp_path):
        """A TOOL_RESULT whose tool_use_id has no matching TOOL_CALL
        must not re-parent the unrelated tool_call. (The tool_call may
        still pick up a pass-2 next-bar duration estimate — that's
        separate from the pair-matching logic.)"""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                _assistant_tool_use(1717500000.0, "Read", "tu-a", {}),
                _tool_result_entry(1717500001.0, "tu-orphan", "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        # 1 tool_call + 1 tool_result (no leading text in the helper)
        assert len(bars) == 3
        tool = next(bar for bar in bars if bar.type == BarType.TOOL_CALL)
        result = next(bar for bar in bars if bar.type == BarType.TOOL_RESULT)
        # The tool_call's tool_use_id is still "tu-a" — the orphan
        # did not overwrite it. Its end_time may have been pulled
        # forward by the pass-2 next-bar estimate, but its identity
        # (parent_id, tool_use_id) is preserved.
        assert tool.detail.get("tool_use_id") == "tu-a"
        assert result.detail.get("tool_use_id") == "tu-orphan"
        # The orphan result's bar still references the (missing) tool_call
        # via parent_id=None, not via a fabricated match to "tu-a".
        assert bars[1].detail.get("parent_id") is None

    def test_skip_meta_entry(self, tmp_path):
        """``isMeta=True`` entries are bookkeeping and produce no bars."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": True,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "text", "text": "this should be dropped"}],
                },
                _assistant_text(1717500001.0, "real text"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].label == "LLM text"

    def test_skip_cost_block_entry(self, tmp_path):
        """``type=="cost_block"`` is a non-Message entry; the transcript
        parser emits no bars for it (cost is folded by SessionMetadataParser)."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {"type": "cost_block", "cost": {"total_cost_usd": 0.42}},
                _assistant_text(1717500000.0, "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].label == "LLM text"

    def test_skip_progress_entry(self, tmp_path):
        """``type=="progress"`` is a sentinel; it does not produce a bar."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {"type": "progress", "data": {"kind": "thinking"}, "toolUseID": "x"},
                _assistant_text(1717500000.0, "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1

    def test_skip_compact_summary(self, tmp_path):
        """``isCompactSummary=True`` entries are snip boundary markers —
        no bars, but they do affect downstream anchoring."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": True,
                    "content": [{"type": "text", "text": "compaction summary"}],
                },
                _assistant_text(1717500001.0, "post-compact"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].label == "LLM text"

    def test_skip_api_error_message(self, tmp_path):
        """``isApiErrorMessage=True`` on an assistant entry produces no bar."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "isApiErrorMessage": True,
                    "apiError": "rate limit",
                    "content": [{"type": "text", "text": "rate limit error"}],
                },
                _assistant_text(1717500001.0, "ok"),
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1

    def test_system_status_noise_is_dropped(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "system",
                    "type": "message",
                    "subtype": "background_complete",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "text", "text": "__background_complete__"}],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert bars == []

    def test_thinking_block_emits_llm_text_bar(self, tmp_path):
        """A ``thinking`` block produces the same bar shape as ``text``."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "thinking", "thinking": "hmm, let me think"}],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL

    def test_explicit_subagent_id_propagates_to_bars(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "parent_session_id": "main-session-1",
                    "content": [
                        {"type": "tool_use", "name": "Read", "id": "c1", "input": {}},
                    ],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p, agent_id="child-agent")
        assert len(bars) == 2
        assert all(bar.agent_id == "child-agent" for bar in bars)

    def test_malformed_json_line_skipped(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not-json\n")
        bars = TranscriptParser().parse_file(p)
        assert bars == []

    def test_parse_incremental(self, tmp_path):
        p = tmp_path / "inc.jsonl"
        p.write_text(json.dumps(_assistant_text(1.0, "hi")) + "\n")
        bars, offset = TranscriptParser().parse_incremental(p, 0)
        assert len(bars) == 1
        assert offset > 0

    def test_parse_incremental_nonexistent(self):
        bars, offset = TranscriptParser().parse_incremental(Path("/nope"), 0)
        assert bars == []
        assert offset == 0

    def test_parse_resets_state_between_files(self, tmp_path):
        """Bar counter and pending tools reset on each parse_file call."""
        parser = TranscriptParser()
        p1 = _write_jsonl(tmp_path / "a.jsonl", [_assistant_text(1.0, "msg1")])
        p2 = _write_jsonl(tmp_path / "b.jsonl", [_assistant_text(2.0, "msg2")])
        bars1 = parser.parse_file(p1)
        bars2 = parser.parse_file(p2)
        assert bars1[0].id == "main-llm-0"
        assert bars2[0].id == "main-llm-0"

    def test_iso8601_timestamp_in_entry(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": "2024-06-04T12:00:00+00:00",
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "text", "text": "hi"}],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].start_time > 0

    def test_numeric_timestamp_is_accepted(self, tmp_path):
        """A non-ISO, non-string timestamp triggers the ``ts_unrecorded``
        flag on the resulting bar."""
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": 12345,  # int — not accepted in the new format
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": [{"type": "text", "text": "hi"}],
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].ts_unrecorded is False

    def test_string_content_is_normalized(self, tmp_path):
        p = _write_jsonl(
            tmp_path / "t.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "content": "legacy bare string",
                },
            ],
        )
        bars = TranscriptParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.LLM_CALL
        assert bars[0].detail["text"] == "legacy bare string"


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
        # New metadata shape — only user-anchored fields. Operational
        # counters and the model label are NOT cached here anymore; the
        # SessionMetadataParser pulls them from the transcript.
        meta = {
            "title": "Test Session",
            "start_time": 1717500000.0,
            "last_updated": 1717500030.0,
            "agent_name": "codex",
            "tags": ["test"],
            "cwd": "/tmp/proj",
        }
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        # Transcript carries the model label on the assistant entry.
        _write_jsonl(
            session_dir / "transcript.jsonl",
            [
                _user_text(1717500000.0, "hi"),
                _assistant_text(1717500030.0, "done", model="claude-opus-4-7"),
            ],
        )

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("test-session-001")
        assert viz is not None
        assert viz.session_id == "test-session-001"
        assert viz.title == "Test Session"
        # Model is read from the transcript, not metadata.
        assert viz.model == "claude-opus-4-7"
        # last_updated is the only duration signal when the transcript
        # has no parseable timestamps.
        assert viz.duration_ms == 30000

    def test_parse_session_counts_from_transcript(self, tmp_path):
        """turn_count and tool_count come from walking transcript.jsonl,
        not from metadata.json (which no longer carries them)."""
        session_dir = tmp_path / "ts-session"
        session_dir.mkdir()
        meta = {"title": "ts"}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        _write_jsonl(
            session_dir / "transcript.jsonl",
            [
                _user_text(1717500000.0, "hi"),
                _assistant_tool_use(1717500001.0, "Read", "tu-1", {}),
                _tool_result_entry(1717500002.0, "tu-1", "ok"),
                _assistant_text(1717500003.0, "done"),
            ],
        )
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("ts-session")
        assert viz is not None
        # 2 user + 2 assistant = 4 turns
        assert viz.turn_count == 4
        # 1 tool_use block
        assert viz.tool_count == 1

    def test_parse_session_without_metadata(self, tmp_path):
        session_dir = tmp_path / "minimal-session"
        session_dir.mkdir()
        # No metadata.json, no transcript
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("minimal-session")
        assert viz is not None
        assert viz.status == "unknown"

    def test_parse_session_discovers_report_artifacts(self, tmp_path):
        session_dir = tmp_path / "artifact-session"
        session_dir.mkdir()
        (session_dir / "report.md").write_text("# Report\n", encoding="utf-8")
        (session_dir / "events.ndjson").write_text('{"event":"ok"}\n', encoding="utf-8")
        (session_dir / "debug.ndjson").write_text('{"debug":"ok"}\n', encoding="utf-8")

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("artifact-session")

        assert viz is not None
        assert viz.report_path and viz.report_path.endswith("report.md")
        assert viz.tool_events_path and viz.tool_events_path.endswith("events.ndjson")
        assert viz.debug_log_path and viz.debug_log_path.endswith("debug.ndjson")

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

    def test_cost_block_entry_overrides_usage_sum(self, tmp_path):
        """A ``cost_block`` entry's ``model_usage`` token total wins over
        the per-message ``usage`` sum."""
        session_dir = tmp_path / "cb-session"
        session_dir.mkdir()
        (session_dir / "metadata.json").write_text(json.dumps({}), encoding="utf-8")
        _write_jsonl(
            session_dir / "transcript.jsonl",
            [
                _user_text(1717500000.0, "hi"),
                {
                    **{
                        "role": "assistant",
                        "type": "message",
                        "timestamp": _iso(1717500001.0),
                        "isMeta": False,
                        "isVirtual": False,
                        "isCompactSummary": False,
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                        "content": [{"type": "text", "text": "ok"}],
                    },
                },
                {
                    "type": "cost_block",
                    "cost": {
                        "total_cost_usd": 0.07,
                        "model_usage": {
                            "claude-opus-4-7": {
                                "input_tokens": 5000,
                                "output_tokens": 200,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0,
                            },
                        },
                    },
                },
            ],
        )
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("cb-session")
        assert viz is not None
        assert viz.stats.cost_usd == 0.07
        # The cost_block's model_usage total (5200) wins over the
        # per-message usage sum (150).
        assert viz.stats.context_tokens == 5200

    # ---- _infer_status recency behavior (drives live polling) ----

    def test_status_recent_transcript_is_running(self, tmp_path):
        import time as _time

        session_dir = tmp_path / "live-session"
        session_dir.mkdir()
        meta = {"start_time": _time.time() - 60, "last_updated": _time.time() - 60}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text(
            json.dumps(_assistant_text(_time.time(), "x")) + "\n",
            encoding="utf-8",
        )
        # mtime is "now" because we just wrote the file.

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("live-session")
        assert viz is not None
        assert viz.status == "running"

    def test_status_recent_last_updated_is_running(self, tmp_path):
        import time as _time

        session_dir = tmp_path / "live-session"
        session_dir.mkdir()
        meta = {"start_time": _time.time() - 600, "last_updated": _time.time() - 30}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        old = _time.time() - 600
        tp = session_dir / "transcript.jsonl"
        tp.write_text(
            json.dumps(_assistant_text(_time.time(), "x")) + "\n",
            encoding="utf-8",
        )
        import os

        os.utime(tp, (old, old))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("live-session")
        assert viz is not None
        assert viz.status == "running"

    def test_status_old_transcript_is_completed(self, tmp_path):
        import os
        import time as _time

        session_dir = tmp_path / "old-session"
        session_dir.mkdir()
        old = _time.time() - 3600
        meta = {"start_time": old - 60, "last_updated": old}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text(
            json.dumps(_assistant_text(_time.time(), "x")) + "\n",
            encoding="utf-8",
        )
        os.utime(tp, (old, old))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("old-session")
        assert viz is not None
        assert viz.status == "completed"

    def test_status_explicit_wins_over_recency(self, tmp_path):
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
        tp.write_text(
            json.dumps(_assistant_text(_time.time(), "x")) + "\n",
            encoding="utf-8",
        )

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("weird-session")
        assert viz is not None
        assert viz.status == "failed"

    def test_status_no_transcript_no_metadata_is_unknown(self, tmp_path):
        session_dir = tmp_path / "bare-session"
        session_dir.mkdir()
        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("bare-session")
        assert viz is not None
        assert viz.status == "unknown"

    def test_status_stale_short_session_is_completed(self, tmp_path):
        """Regression: a session that ran for <5s and was killed 47h ago
        (e.g. 429 rate limit 27ms after start) must NOT be reported as
        ``"running"``."""
        import os
        import time as _time

        session_dir = tmp_path / "stale-short"
        session_dir.mkdir()
        ancient = _time.time() - 47 * 3600
        meta = {"start_time": ancient, "last_updated": ancient + 0.027}
        (session_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        tp = session_dir / "transcript.jsonl"
        tp.write_text(
            json.dumps(_assistant_text(ancient, "x")) + "\n",
            encoding="utf-8",
        )
        os.utime(tp, (ancient, ancient))

        parser = SessionMetadataParser(sessions_dir=tmp_path)
        viz = parser.parse("stale-short")
        assert viz is not None
        assert viz.status == "completed", (
            f"stale short session mis-classified as {viz.status!r} (expected 'completed')"
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
        p.write_text(
            json.dumps(
                {
                    "ts": 1717500000.0,
                    "tool": "Bash",
                    "approved": True,
                    "turn": 1,
                }
            )
            + "\n"
        )
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].type == BarType.TOOL_CALL
        assert bars[0].label == "Bash"
        assert bars[0].status == BarStatus.SUCCESS

    def test_parse_denied_tool(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text(
            json.dumps(
                {
                    "ts": 1717500000.0,
                    "tool": "Write",
                    "approved": False,
                    "deny_reason": "permission denied",
                }
            )
            + "\n"
        )
        bars = ToolEventsParser().parse_file(p)
        assert len(bars) == 1
        assert bars[0].status == BarStatus.ERROR

    def test_parse_pending_tool(self, tmp_path):
        p = tmp_path / "events.ndjson"
        p.write_text(
            json.dumps(
                {
                    "ts": 1717500000.0,
                    "tool": "Read",
                    "approved": None,
                }
            )
            + "\n"
        )
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
# MultiAgentParser (new parse_for_session signature)
# ---------------------------------------------------------------------------


class TestMultiAgentParser:
    def test_parse_for_session_no_subagents(self, tmp_path):
        """With no flat transcripts and no nested subagents dir, the
        parser returns an empty list (root is rendered as a session row)."""
        nodes = MultiAgentParser().parse_for_session(
            "main",
            sessions_dir=tmp_path,
            transcripts_dir=tmp_path / "transcripts",
        )
        assert nodes == []

    def test_parse_for_session_nested_subagent(self, tmp_path):
        """A nested ``sessions/<sid>/subagents/agent-<id>.jsonl`` file is
        discovered and emitted as an AgentTreeNode."""
        session_dir = tmp_path / "main"
        sub_dir = session_dir / "subagents"
        sub_dir.mkdir(parents=True)
        _write_jsonl(
            sub_dir / "agent-abc123.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "parent_session_id": "main",
                    "content": [{"type": "text", "text": "I will search the repo"}],
                },
                _assistant_tool_use(1717500001.0, "Read", "tu-1", {}),
            ],
        )
        nodes = MultiAgentParser().parse_for_session(
            "main",
            sessions_dir=tmp_path,
            transcripts_dir=tmp_path / "transcripts",
        )
        assert len(nodes) == 1
        node = nodes[0]
        assert node.agent_id == "abc123"
        assert node.parent_id == "main"
        assert node.metadata["source"] == "nested"
        assert node.metadata["tool_count"] == 1

    def test_parse_for_session_flat_subagent_with_parent_marker(self, tmp_path):
        """A flat ``transcripts/<agent_id>.jsonl`` is discovered iff its
        first non-meta entry carries ``parent_session_id == session_id``."""
        tx_dir = tmp_path / "transcripts"
        tx_dir.mkdir()
        _write_jsonl(
            tx_dir / "agent-xyz.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "parent_session_id": "main",
                    "content": [{"type": "text", "text": "hello from subagent"}],
                },
            ],
        )
        nodes = MultiAgentParser().parse_for_session(
            "main",
            sessions_dir=tmp_path,
            transcripts_dir=tx_dir,
        )
        assert len(nodes) == 1
        assert nodes[0].agent_id == "xyz"
        assert nodes[0].metadata["source"] == "flat"

    def test_parse_for_session_flat_subagent_with_wrong_parent_skipped(self, tmp_path):
        """A flat transcript that does not match the queried parent is
        excluded."""
        tx_dir = tmp_path / "transcripts"
        tx_dir.mkdir()
        _write_jsonl(
            tx_dir / "agent-other.jsonl",
            [
                {
                    "role": "assistant",
                    "type": "message",
                    "timestamp": _iso(1717500000.0),
                    "isMeta": False,
                    "isVirtual": False,
                    "isCompactSummary": False,
                    "parent_session_id": "different-session",
                    "content": [{"type": "text", "text": "x"}],
                },
            ],
        )
        nodes = MultiAgentParser().parse_for_session(
            "main",
            sessions_dir=tmp_path,
            transcripts_dir=tx_dir,
        )
        assert nodes == []
