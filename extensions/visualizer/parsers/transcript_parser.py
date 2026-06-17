"""Transcript JSONL incremental parser (F-91-B).

Streaming parser for transcript.jsonl files using file.seek + readlines
for memory-efficient incremental reads of large sessions.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.viz_models import BarStatus, BarType, TimelineBar

logger = logging.getLogger(__name__)


def _coerce_timestamp(value: Any) -> float:
    """Coerce a transcript timestamp value to a float Unix epoch.

    Accepts:
      - float / int: returned as-is
      - ISO 8601 string: parsed via ``datetime.fromisoformat``
      - None / unparseable: returns 0.0
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            # ``Z`` suffix is not handled by fromisoformat in Python <3.11
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            logger.debug("Unparseable transcript timestamp: %r", value)
            return 0.0
    return 0.0


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
        from ..builders.operation_categorizer import OperationCategorizer

        self._bar_counter = 0
        self._turn_counter = 0
        self._last_timestamp: float | None = None
        self._pending_tools: dict[str, dict[str, Any]] = {}
        self._categorizer = OperationCategorizer()

    def parse_file(self, path: Path | str) -> list[TimelineBar]:
        """Parse an entire transcript.jsonl file into bars."""
        path = Path(path)
        if not path.exists():
            return []
        # Reset per-file state so concurrent calls on a shared parser
        # don't leak bar counters or pending tool pairs across sessions.
        self._bar_counter = 0
        self._turn_counter = 0
        self._last_timestamp = None
        self._pending_tools = {}
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
                entry_bars = self._entry_to_bars(entry, line_num)
                if entry_bars:
                    bars.extend(entry_bars)
        # Backfill TOOL_CALL bar durations from matching TOOL_RESULT bars.
        # _tool_use_bar() emits a placeholder bar with duration_ms=0
        # (the result hasn't been seen yet); _tool_result_bar() emits a
        # separate bar carrying the actual latency. After the full file
        # is parsed, copy the resolved end_time + duration_ms back onto
        # the TOOL_CALL bar so per-tool timing in the gantt / stats bar
        # reflects real tool latency instead of 0.
        self._pair_tool_durations(bars)
        # Backfill LLM_TEXT bar durations — _text_bar() emits placeholders
        # (duration_ms=100) because at parse time the next entry's timestamp
        # is unknown. Resolve from the gap to the next bar in the timeline.
        self._pair_llm_text_durations(bars)
        return bars

    def _pair_tool_durations(self, bars: list[TimelineBar]) -> None:
        """Resolve TOOL_CALL bar durations.

        Two passes:

        1. **Primary** — copy ``end_time`` / ``duration_ms`` from the
           matching ``TOOL_RESULT`` bar (matched by ``tool_use_id``)
           back onto the ``TOOL_CALL``. Happy path.

        2. **Fallback** — for any ``TOOL_CALL`` still at ``duration_ms
           == 0`` after pass 1, estimate the duration from the *next*
           bar's ``start_time``. This covers real-world transcripts where
           the ``TOOL_RESULT`` block was never persisted: the session
           was killed mid-tool, the result is in a different log
           channel, or the upstream writer only emits ``tool_use``
           events. The next bar's ``start_time`` is when the next
           operation began — a reasonable upper bound on the tool's
           actual latency (the agent had to wait at least this long for
           the tool to return control before doing the next thing).

        Only ``TOOL_CALL`` bars whose ``duration_ms`` is still 0 are
        touched, so a future path that pre-fills a duration (e.g. live
        tail with the result already in flight) is preserved. In pass
        1, the first ``TOOL_CALL`` occurrence wins so a malformed
        replay with duplicate ``tool_use_id`` values doesn't clobber
        an earlier bar.
        """
        # ---- Pass 1: tool_use ↔ tool_result pairing ----
        tool_use_index: dict[str, int] = {}
        for i, bar in enumerate(bars):
            if bar.type != BarType.TOOL_CALL:
                continue
            tuid = bar.detail.get("tool_use_id") if isinstance(bar.detail, dict) else None
            if tuid and tuid not in tool_use_index:
                tool_use_index[tuid] = i

        for bar in bars:
            if bar.type != BarType.TOOL_RESULT:
                continue
            tuid = bar.detail.get("tool_use_id") if isinstance(bar.detail, dict) else None
            if not tuid:
                continue
            idx = tool_use_index.get(tuid)
            if idx is None:
                continue
            tool_call_bar = bars[idx]
            if tool_call_bar.duration_ms != 0 or bar.duration_ms <= 0:
                continue
            tool_call_bar.end_time = bar.end_time
            tool_call_bar.duration_ms = bar.duration_ms

        # ---- Pass 2: next-bar estimate for still-zero tool_call bars ----
        # Find the first *strictly later* bar. Sibling tool_use blocks
        # emitted in the same entry share ``start_time`` (parallel
        # calls dispatched together); using one as the estimate for
        # another would yield 0ms and look like the placeholder
        # we were trying to fix. Skip until we find a bar with
        # ``start_time > bar.start_time``.
        for i, bar in enumerate(bars):
            if bar.type != BarType.TOOL_CALL or bar.duration_ms != 0:
                continue
            for j in range(i + 1, len(bars)):
                nxt = bars[j]
                if nxt.id == bar.id:
                    continue
                if nxt.start_time <= bar.start_time:
                    # Parallel sibling in the same entry — keep looking.
                    continue
                bar.end_time = nxt.start_time
                bar.duration_ms = int((nxt.start_time - bar.start_time) * 1000)
                break  # only the first strictly-later next-bar is consulted

    def _pair_llm_text_durations(self, bars: list[TimelineBar]) -> None:
        """Backfill LLM_TEXT bar durations from the next bar's start time.

        ``_text_bar()`` emits placeholder bars (``duration_ms=100``,
        ``end_time = start_time + 0.1s``) because at parse time the
        next entry's timestamp isn't known yet. After the full file
        is parsed, this pass resolves the actual text-generation span
        from each LLM_TEXT bar's start_time to the start of the next
        bar in chronological order.

        Bars within the same transcript entry (text + tool_use blocks)
        share the same timestamp, so they are skipped (their duration
        is covered by the very next *different* entry's timestamp).
        """
        text_bars = [b for b in bars if b.type == BarType.LLM_CALL]
        if not text_bars:
            return

        # Build a sorted index (start_time, id) of all bars for lookup
        all_sorted = sorted(bars, key=lambda b: (b.start_time, b.id))

        for text_bar in text_bars:
            # Find the first bar that starts strictly after this text_bar.
            # 1ms epsilon avoids self-matching on floating point rounding
            # and skips sibling bars from the same transcript entry.
            for next_bar in all_sorted:
                if next_bar.start_time > text_bar.start_time + 0.001:
                    duration_ms = int(
                        (next_bar.start_time - text_bar.start_time) * 1000
                    )
                    if duration_ms >= 100:  # only update if materially longer
                        text_bar.end_time = next_bar.start_time
                        text_bar.duration_ms = duration_ms
                        # Real gap was resolved; the 100ms placeholder
                        # the bar was created with is no longer in effect.
                        # Clear the flag so the bezier view drops the
                        # '未记录' label and uses the resolved width.
                        text_bar.duration_unrecorded = False
                    break

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
            entry_bars = self._entry_to_bars(entry, line_num)
            if entry_bars:
                bars.extend(entry_bars)

        return bars, new_offset

    def _entry_to_bars(self, entry: dict[str, Any], line_num: int) -> list[TimelineBar]:
        """Convert a single transcript entry to one or more TimelineBars.

        A single entry can carry multiple content blocks (Anthropic API
        format: ``[text, tool_use, tool_use, ...]``). All non-empty blocks
        are returned as separate bars so per-tool stats, the gantt, and
        the duration-backfill pass see the full timeline.

        The earlier "first bar per entry" simplification dropped the
        rest of the blocks, which made Avg Duration stats come out
        artificially low and hid parallel tool_use calls from the gantt.
        """
        role = entry.get("role", "")
        msg_type = entry.get("type", "")
        content = entry.get("content", [])
        raw_ts = entry.get("_timestamp") or entry.get("timestamp")

        if raw_ts is None:
            # Derive timestamp from line number for ordering
            timestamp = self._last_timestamp or 0.0
        else:
            timestamp = _coerce_timestamp(raw_ts)

        # Always track the most recent timestamp for next entry
        self._last_timestamp = timestamp

        # ts_unrecorded: when the upstream record had no parseable
        # timestamp the bar's time fields are unreliable. The bezier
        # view labels all of them '未记录' when this flag is set.
        ts_unrecorded = timestamp <= 0.0
        # Model label is carried on the entry (Claude Code puts it next
        # to the role, not inside individual content blocks). Forwarded
        # to per-block helpers so LLM bars carry it.
        entry_model = entry.get("model") if isinstance(entry, dict) else None

        # System role (compact / away_summary / local_command / etc.):
        # emit a single CUSTOM bar carrying the subtype and optional
        # text payload. Previously dropped here, which made bezier view
        # unable to surface these points in the timeline.
        if role == "system":
            bar = self._system_bar(entry, timestamp, ts_unrecorded=ts_unrecorded)
            return [bar] if bar else []

        # Unknown roles (e.g. synthetic ``__background_complete__``
        # sentinels from the upstream writer) are still skipped — they
        # carry no payload worth surfacing.
        if role not in ("assistant", "user"):
            return []

        # Handle tool_use blocks (inside assistant messages)
        if isinstance(content, list):
            bars: list[TimelineBar] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "tool_use":
                    bar = self._tool_use_bar(block, timestamp, ts_unrecorded=ts_unrecorded)
                    if bar:
                        bars.append(bar)
                elif btype == "tool_result":
                    bar = self._tool_result_bar(block, timestamp, ts_unrecorded=ts_unrecorded)
                    if bar:
                        bars.append(bar)
                elif btype == "text":
                    # LLM text generation bar
                    bar = self._text_bar(
                        block, timestamp,
                        model=entry_model,
                        ts_unrecorded=ts_unrecorded,
                    )
                    if bar:
                        bars.append(bar)
            return bars

        # Plain text messages (assistant/user with string content)
        text = content if isinstance(content, str) else ""
        if not text:
            return []
        return [self._message_bar(role, text, timestamp, ts_unrecorded=ts_unrecorded)]


    def _tool_use_bar(
        self, block: dict[str, Any], ts: float, *, ts_unrecorded: bool = False,
    ) -> TimelineBar | None:
        """Create a bar for a tool_use block."""
        tool_name = block.get("name", "unknown")
        tool_use_id = block.get("id") or block.get("tool_use_id", "")
        self._bar_counter += 1
        bar_id = f"tu-{self._bar_counter}"
        # Store pending for pairing with result later
        self._pending_tools[tool_use_id] = {
            "id": bar_id,
            "tool_name": tool_name,
            "start_time": ts,
        }
        bar = TimelineBar(
            id=bar_id,
            type=BarType.TOOL_CALL,
            label=tool_name,
            start_time=ts,
            end_time=ts,  # Will be updated when result arrives
            duration_ms=0,
            status=BarStatus.RUNNING,
            detail={"tool_use_id": tool_use_id, "params": block.get("input", {})},
            color=self._TOOL_COLORS.get(tool_name),
            ts_unrecorded=ts_unrecorded,
        )
        bar.category = self._categorizer.categorize(bar)
        return bar

    def _tool_result_bar(
        self, block: dict[str, Any], ts: float, *, ts_unrecorded: bool = False,
    ) -> TimelineBar | None:
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
            ts_unrecorded=ts_unrecorded,
        )

    def _text_bar(
        self,
        block: dict[str, Any],
        ts: float,
        *,
        model: str | None = None,
        ts_unrecorded: bool = False,
    ) -> TimelineBar | None:
        """Create a bar for assistant text generation.

        ``duration_unrecorded=True`` is set at creation: the 100 ms
        placeholder is a synthetic span, not a real measurement. The
        backfill pass in ``_pair_llm_text_durations`` clears the flag
        when it resolves a real gap to the next bar.
        """
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
            model=model,
            duration_unrecorded=True,
            ts_unrecorded=ts_unrecorded,
        )

    def _message_bar(
        self, role: str, text: str, ts: float, *, ts_unrecorded: bool = False,
    ) -> TimelineBar:
        """Create a generic message bar.

        ``duration_unrecorded=True`` always: plain-text messages have
        no real duration. The bezier view renders the bar at minimum
        visible width and labels the duration '未记录'.
        """
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
            user_role=role if role in ("user", "assistant") else None,
            user_text=text[:200] if role == "user" else None,
            duration_unrecorded=True,
            ts_unrecorded=ts_unrecorded,
        )

    def _system_bar(
        self, entry: dict[str, Any], ts: float, *, ts_unrecorded: bool = False,
    ) -> TimelineBar | None:
        """Create a bar for a system-injected event.

        System entries (compact, away_summary, local_command, etc.)
        carry a ``subtype`` discriminator and an optional text payload
        in the content field. We emit a point-in-time bar (zero real
        duration) so the bezier view can render the marker without
        inflating the timeline.
        """
        # Subtype: prefer explicit 'subtype', fall back to 'type' for
        # older transcripts that used the latter.
        subtype = (
            entry.get("subtype")
            or entry.get("type")
            or "system"
        )
        content = entry.get("content", "")
        if isinstance(content, list):
            # Join text blocks if a list payload
            content = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("text")
            )
        system_text = content[:200] if isinstance(content, str) else None

        self._bar_counter += 1
        return TimelineBar(
            id=f"sys-{self._bar_counter}",
            type=BarType.CUSTOM,
            label=f"system:{subtype}",
            start_time=ts,
            end_time=ts,
            duration_ms=0,
            status=BarStatus.SUCCESS,
            detail={"subtype": subtype, "text_preview": system_text or ""},
            user_role="system",
            system_text=system_text,
            duration_unrecorded=True,
            ts_unrecorded=ts_unrecorded,
        )
