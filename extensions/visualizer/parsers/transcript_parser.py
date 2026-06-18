"""Transcript JSONL parser for the new ClawCodeX session format.

Reads ``transcript.jsonl`` files produced by the new
``src/services/session_storage.py`` (JSONL of typed ``Message``
dicts) and converts each entry into one or more ``TimelineBar`` rows
for the gantt / waterfall view.

Format assumptions (matches ``src.types.messages.message_to_dict``):

- Each line is a JSON object with a ``role`` and ``content`` (always a
  list of typed content blocks in the new format).
- ``content`` blocks are tagged with ``type``: ``text`` / ``tool_use`` /
  ``tool_result`` / ``thinking`` / ``image`` / ``document`` / etc.
- ``timestamp`` is an ISO 8601 string (e.g. ``2026-06-16T20:20:07.531654``).
- ``isMeta`` / ``isVirtual`` / ``isCompactSummary`` / ``isApiErrorMessage``
  are flags that gate whether an entry counts.
- ``type == "cost_block"`` is a special non-Message entry used to embed
  the cumulative cost; it is skipped here (the SessionMetadataParser
  already folds the cost into the ``SessionVizData``).
- ``type == "progress"`` is a non-Message sentinel; it is skipped.
- ``model`` (on assistant) and ``usage`` (per-message token usage) are
  carried on the entry and forwarded to the bar.
- ``parent_session_id`` marks sub-agent entries and is forwarded into
  the bar's ``agent_id`` detail so the multi-session view can group
  sub-agent activity.

No backward-compat shims for the legacy envelope (``content`` as string
+ ``tool_calls`` / ``tool_call_id`` keys) — the new format unifies the
shape and the old envelope is no longer emitted.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.viz_models import BarStatus, BarType, TimelineBar

logger = logging.getLogger(__name__)


def _coerce_iso_timestamp(value: Any) -> float:
    """Coerce an ISO 8601 string timestamp to a float Unix epoch.

    Returns 0.0 for anything unparseable. The new format only writes
    ISO 8601 timestamps, so we deliberately do not accept float epochs
    (those were a legacy wire-format quirk).
    """
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        logger.debug("Unparseable transcript timestamp: %r", value)
        return 0.0


class TranscriptParser:
    """Streaming parser for the new transcript format."""

    # Tool call color palette — kept identical to the old definition so
    # the front-end legend and existing snapshots stay consistent.
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

    # ------------------------------------------------------------------
    # File-level parsing
    # ------------------------------------------------------------------

    def parse_file(self, path: Path | str) -> list[TimelineBar]:
        """Parse an entire transcript.jsonl file into ``TimelineBar``s."""
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
                if not isinstance(entry, dict):
                    continue
                entry_bars = self._entry_to_bars(entry, line_num)
                if entry_bars:
                    bars.extend(entry_bars)
        # Backfill TOOL_CALL bar durations from matching TOOL_RESULT
        # bars. Same algorithm as before — tool_use emits a 0-duration
        # placeholder, tool_result stamps the real end_time.
        self._pair_tool_durations(bars)
        # Backfill LLM_TEXT bar durations from the next bar's start.
        self._pair_llm_text_durations(bars)
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
            entry_bars = self._entry_to_bars(entry, line_num)
            if entry_bars:
                bars.extend(entry_bars)

        return bars, new_offset

    # ------------------------------------------------------------------
    # Per-entry conversion
    # ------------------------------------------------------------------

    def _entry_to_bars(
        self,
        entry: dict[str, Any],
        line_num: int,
    ) -> list[TimelineBar]:
        """Convert a single transcript entry to one or more ``TimelineBar``s.

        Gates applied before bar emission:

        - ``type == "cost_block"`` → no bars (cost is folded by the
          SessionMetadataParser).
        - ``type == "progress"`` → no bars (sentinel; not a real
          conversation turn).
        - ``isMeta`` / ``isVirtual`` → no bars (excluded by design;
          these entries are bookkeeping, not real activity).
        - ``isCompactSummary`` → no bars (anchor for snip boundary;
          SessionMetadataParser handles the windowing).
        - ``isApiErrorMessage`` on assistant → no bars (failure event;
          surfaced as an anomaly elsewhere, not as a turn / tool).
        """
        entry_type = entry.get("type", "")
        if entry_type == "cost_block":
            return []
        if entry_type == "progress":
            return []
        if entry.get("isMeta") or entry.get("isVirtual"):
            return []
        if entry.get("isCompactSummary"):
            return []
        if entry.get("isApiErrorMessage"):
            return []

        role = entry.get("role", "")
        if role not in ("user", "assistant", "system"):
            return []

        timestamp = _coerce_iso_timestamp(entry.get("timestamp"))
        if timestamp <= 0.0:
            timestamp = self._last_timestamp or 0.0
        else:
            self._last_timestamp = timestamp

        ts_unrecorded = timestamp <= 0.0
        entry_model = entry.get("model") if isinstance(entry, dict) else None

        # Track agent_id from parent_session_id (sub-agent transcripts
        # set this; main sessions don't).
        subagent_id = entry.get("parent_session_id")

        if role == "system":
            bar = self._system_bar(entry, timestamp, ts_unrecorded=ts_unrecorded)
            return [bar] if bar else []

        content = entry.get("content")
        if not isinstance(content, list):
            # The new format always serialises content as a list of
            # blocks (see TranscriptWriter._serialize_message which
            # wraps string content as a single text block). Anything
            # else is a malformed line — skip rather than guess.
            return []

        bars: list[TimelineBar] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "tool_use":
                bar = self._tool_use_bar(
                    block,
                    timestamp,
                    ts_unrecorded=ts_unrecorded,
                    subagent_id=subagent_id,
                )
                if bar:
                    bars.append(bar)
            elif btype == "tool_result":
                bar = self._tool_result_bar(
                    block,
                    timestamp,
                    ts_unrecorded=ts_unrecorded,
                    subagent_id=subagent_id,
                )
                if bar:
                    bars.append(bar)
            elif btype in ("text", "thinking"):
                # LLM text / reasoning span — same bar shape.
                bar = self._text_bar(
                    block,
                    timestamp,
                    model=entry_model,
                    ts_unrecorded=ts_unrecorded,
                    subagent_id=subagent_id,
                )
                if bar:
                    bars.append(bar)
            elif btype in ("image", "document"):
                # Image / document attachments are user input side;
                # emit as a CUSTOM bar so the waterfall can show
                # their position without inflating the tool stats.
                self._bar_counter += 1
                bar = TimelineBar(
                    id=f"att-{self._bar_counter}",
                    type=BarType.CUSTOM,
                    label=btype,
                    start_time=timestamp,
                    end_time=timestamp + 0.05,
                    duration_ms=50,
                    status=BarStatus.SUCCESS,
                    detail={"block_type": btype},
                    duration_unrecorded=True,
                    ts_unrecorded=ts_unrecorded,
                )
                if subagent_id:
                    bar.agent_id = str(subagent_id)
                bars.append(bar)
        return bars

    # ------------------------------------------------------------------
    # Block-level helpers
    # ------------------------------------------------------------------

    def _tool_use_bar(
        self,
        block: dict[str, Any],
        ts: float,
        *,
        ts_unrecorded: bool = False,
        subagent_id: Any = None,
    ) -> TimelineBar | None:
        """Create a bar for a ``tool_use`` block."""
        tool_name = block.get("name", "unknown")
        tool_use_id = block.get("id", "")
        if not tool_use_id:
            return None
        self._bar_counter += 1
        bar_id = f"tu-{self._bar_counter}"
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
            end_time=ts,  # Resolved by _pair_tool_durations when the result arrives
            duration_ms=0,
            status=BarStatus.RUNNING,
            detail={"tool_use_id": tool_use_id, "params": block.get("input", {})},
            color=self._TOOL_COLORS.get(tool_name),
            ts_unrecorded=ts_unrecorded,
        )
        if subagent_id:
            bar.agent_id = str(subagent_id)
        bar.category = self._categorizer.categorize(bar)
        return bar

    def _tool_result_bar(
        self,
        block: dict[str, Any],
        ts: float,
        *,
        ts_unrecorded: bool = False,
        subagent_id: Any = None,
    ) -> TimelineBar | None:
        """Create a bar for a ``tool_result`` block."""
        tool_use_id = block.get("tool_use_id", "")
        if not tool_use_id:
            return None
        pending = self._pending_tools.pop(tool_use_id, None)
        start_time = pending["start_time"] if pending else ts
        duration_ms = max(0, int((ts - start_time) * 1000))
        is_error = bool(block.get("is_error"))
        status = BarStatus.ERROR if is_error else BarStatus.SUCCESS

        self._bar_counter += 1
        content = block.get("content", "")
        if isinstance(content, list):
            excerpt = (
                "\n".join(
                    str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("text")
                )[:200]
                or "..."
            )
        elif isinstance(content, str):
            excerpt = content[:200]
        else:
            excerpt = "..."

        bar = TimelineBar(
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
                "duration_ms": block.get("duration_ms"),
            },
            ts_unrecorded=ts_unrecorded,
        )
        if subagent_id:
            bar.agent_id = str(subagent_id)
        return bar

    def _text_bar(
        self,
        block: dict[str, Any],
        ts: float,
        *,
        model: str | None = None,
        ts_unrecorded: bool = False,
        subagent_id: Any = None,
    ) -> TimelineBar | None:
        """Create a bar for an assistant text or thinking block.

        ``duration_unrecorded=True`` at creation: the 100 ms placeholder
        is synthetic. ``_pair_llm_text_durations`` clears the flag when
        it resolves a real gap to the next bar.
        """
        text = block.get("text") or block.get("thinking") or ""
        if not text:
            return None
        self._bar_counter += 1
        bar = TimelineBar(
            id=f"txt-{self._bar_counter}",
            type=BarType.LLM_CALL,
            label="LLM text",
            start_time=ts,
            end_time=ts + 0.1,
            duration_ms=100,
            status=BarStatus.SUCCESS,
            detail={"text_preview": text[:200]},
            model=model,
            duration_unrecorded=True,
            ts_unrecorded=ts_unrecorded,
        )
        if subagent_id:
            bar.agent_id = str(subagent_id)
        return bar

    def _system_bar(
        self,
        entry: dict[str, Any],
        ts: float,
        *,
        ts_unrecorded: bool = False,
    ) -> TimelineBar | None:
        """Create a bar for a system-injected event."""
        subtype = entry.get("subtype") or entry.get("type") or "system"
        content = entry.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content if isinstance(b, dict) and b.get("text")
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

    # ------------------------------------------------------------------
    # Post-processing: resolve tool_call and llm_text durations
    # ------------------------------------------------------------------

    def _pair_tool_durations(self, bars: list[TimelineBar]) -> None:
        """Resolve TOOL_CALL bar durations from matching TOOL_RESULT bars.

        Two passes (see git blame on the prior implementation):

        1. **Primary** — copy ``end_time`` / ``duration_ms`` from the
           matching ``TOOL_RESULT`` bar (matched by ``tool_use_id``)
           back onto the ``TOOL_CALL``.

        2. **Fallback** — for any ``TOOL_CALL`` still at
           ``duration_ms == 0`` after pass 1, estimate from the next
           bar's ``start_time``.
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
        for i, bar in enumerate(bars):
            if bar.type != BarType.TOOL_CALL or bar.duration_ms != 0:
                continue
            for j in range(i + 1, len(bars)):
                nxt = bars[j]
                if nxt.id == bar.id:
                    continue
                if nxt.start_time <= bar.start_time:
                    continue
                bar.end_time = nxt.start_time
                bar.duration_ms = int((nxt.start_time - bar.start_time) * 1000)
                break

    def _pair_llm_text_durations(self, bars: list[TimelineBar]) -> None:
        """Backfill LLM_TEXT bar durations from the next bar's start time."""
        text_bars = [b for b in bars if b.type == BarType.LLM_CALL]
        if not text_bars:
            return

        all_sorted = sorted(bars, key=lambda b: (b.start_time, b.id))

        for text_bar in text_bars:
            for next_bar in all_sorted:
                if next_bar.start_time > text_bar.start_time + 0.001:
                    duration_ms = int((next_bar.start_time - text_bar.start_time) * 1000)
                    if duration_ms >= 100:
                        text_bar.end_time = next_bar.start_time
                        text_bar.duration_ms = duration_ms
                        text_bar.duration_unrecorded = False
                    break
