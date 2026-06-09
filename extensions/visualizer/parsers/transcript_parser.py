"""Transcript JSONL incremental parser (F-91-B).

Streaming parser for transcript.jsonl files using file.seek + readlines
for memory-efficient incremental reads of large sessions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import BarStatus, BarType, TimelineBar

logger = logging.getLogger(__name__)


class TranscriptParser:
    """Incremental transcript parser that produces TimelineBar objects.

    Supports both full-parse and incremental (tail) modes.
    """

    # Tool call color palette
    _TOOL_COLORS: dict[str, str] = {
        "Read": "#5470c6",
        "Write": "#91cc75",
        "Edit": "#fac858",
        "Bash": "#ee6666",
        "Grep": "#73c0de",
        "Glob": "#3ba272",
        "WebFetch": "#fc8452",
        "WebSearch": "#9a60b4",
        "TodoWrite": "#ea7ccc",
        "TaskStop": "#ff9f7f",
    }

    def __init__(self) -> None:
        self._bar_counter = 0
        self._turn_counter = 0
        self._last_timestamp: float | None = None
        self._pending_tools: dict[str, dict[str, Any]] = {}

    def parse_file(self, path: Path | str) -> list[TimelineBar]:
        """Parse an entire transcript.jsonl file into bars."""
        path = Path(path)
        if not path.exists():
            return []
        bars: list[TimelineBar] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Malformed JSONL line %d", line_num)
                    continue
                bar = self._entry_to_bar(entry, line_num)
                if bar is not None:
                    bars.append(bar)
        return bars

    def parse_incremental(
        self,
        path: Path | str,
        last_offset: int = 0,
    ) -> tuple[list[TimelineBar], int]:
        """Parse new lines since last_offset. Returns (bars, new_offset)."""
        path = Path(path)
        if not path.exists():
            return [], 0

        bars: list[TimelineBar] = []
        with open(path, "r", encoding="utf-8") as f:
            f.seek(last_offset)
            lines = f.readlines()
            new_offset = f.tell()

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            bar = self._entry_to_bar(entry, line_num)
            if bar is not None:
                bars.append(bar)

        return bars, new_offset

    def _entry_to_bar(self, entry: dict[str, Any], line_num: int) -> TimelineBar | None:
        """Convert a single transcript entry to a TimelineBar."""
        role = entry.get("role", "")
        msg_type = entry.get("type", "")
        content = entry.get("content", [])
        timestamp = entry.get("_timestamp") or entry.get("timestamp")

        if timestamp is None:
            # Derive timestamp from line number for ordering
            timestamp = self._last_timestamp or 0.0

        # Handle tool_use blocks (inside assistant messages)
        if role == "assistant" and isinstance(content, list):
            bars: list[TimelineBar] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "tool_use":
                    bar = self._tool_use_bar(block, timestamp)
                    if bar:
                        bars.append(bar)
                elif btype == "text":
                    # LLM text generation bar
                    bar = self._text_bar(block, timestamp)
                    if bar:
                        bars.append(bar)
            # Return the first bar or a composite placeholder
            if bars:
                return bars[0]  # Simplified: first bar per entry

        # Handle tool_result blocks
        if role == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    return self._tool_result_bar(block, timestamp)

        # Plain text messages (assistant/user)
        if role in ("assistant", "user"):
            text = entry.get("content", "")
            if isinstance(text, str) and text:
                return self._message_bar(role, text, timestamp)

        self._last_timestamp = timestamp
        return None

    def _tool_use_bar(self, block: dict[str, Any], ts: float) -> TimelineBar | None:
        """Create a bar for a tool_use block."""
        tool_name = block.get("name", "unknown")
        tool_use_id = block.get("tool_use_id", "")
        self._bar_counter += 1
        bar_id = f"tu-{self._bar_counter}"
        # Store pending for pairing with result later
        self._pending_tools[tool_use_id] = {
            "id": bar_id,
            "tool_name": tool_name,
            "start_time": ts,
        }
        return TimelineBar(
            id=bar_id,
            type=BarType.TOOL_CALL,
            label=tool_name,
            start_time=ts,
            end_time=ts,  # Will be updated when result arrives
            duration_ms=0,
            status=BarStatus.RUNNING,
            detail={"tool_use_id": tool_use_id, "params": block.get("input", {})},
            color=self._TOOL_COLORS.get(tool_name),
        )

    def _tool_result_bar(self, block: dict[str, Any], ts: float) -> TimelineBar | None:
        """Create a bar for a tool_result block."""
        tool_use_id = block.get("tool_use_id", "")
        pending = self._pending_tools.pop(tool_use_id, None)
        start_time = pending["start_time"] if pending else ts
        duration_ms = max(0, int((ts - start_time) * 1000))
        is_error = block.get("is_error", False)
        status = BarStatus.ERROR if is_error else BarStatus.SUCCESS

        self._bar_counter += 1
        content = block.get("content", "")
        excerpt = content[:200] if isinstance(content, str) else "..."

        return TimelineBar(
            id=f"tr-{self._bar_counter}",
            type=BarType.TOOL_RESULT,
            label="result",
            start_time=start_time,
            end_time=ts,
            duration_ms=duration_ms,
            status=status,
            detail={
                "tool_use_id": tool_use_id,
                "excerpt": excerpt,
                "parent_id": pending["id"] if pending else None,
            },
        )

    def _text_bar(self, block: dict[str, Any], ts: float) -> TimelineBar | None:
        """Create a bar for assistant text generation."""
        text = block.get("text", "")
        if not text:
            return None
        self._bar_counter += 1
        return TimelineBar(
            id=f"txt-{self._bar_counter}",
            type=BarType.LLM_CALL,
            label="LLM text",
            start_time=ts,
            end_time=ts + 0.1,  # Approximate
            duration_ms=100,
            status=BarStatus.SUCCESS,
            detail={"text_preview": text[:200]},
        )

    def _message_bar(self, role: str, text: str, ts: float) -> TimelineBar:
        """Create a generic message bar."""
        self._bar_counter += 1
        return TimelineBar(
            id=f"msg-{self._bar_counter}",
            type=BarType.CUSTOM,
            label=role,
            start_time=ts,
            end_time=ts + 0.05,
            duration_ms=50,
            status=BarStatus.SUCCESS,
            detail={"text_preview": text[:200]},
        )
