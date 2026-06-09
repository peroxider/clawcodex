"""Tool events NDJSON parser (F-91-B / F-45).

Parses events.ndjson files produced by AgentRunner._append_tool_event_log.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import BarStatus, BarType, TimelineBar

logger = logging.getLogger(__name__)


class ToolEventsParser:
    """Parse tool-event audit logs into TimelineBars."""

    def __init__(self) -> None:
        self._bar_counter = 0

    def parse_file(self, path: Path | str) -> list[TimelineBar]:
        """Parse an entire events.ndjson file."""
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
                    continue
                bar = self._entry_to_bar(entry)
                if bar is not None:
                    bars.append(bar)
        return bars

    def _entry_to_bar(self, entry: dict[str, Any]) -> TimelineBar | None:
        ts = entry.get("ts", 0.0)
        tool = entry.get("tool", "unknown")
        approved = entry.get("approved")
        deny_reason = entry.get("deny_reason")
        turn = entry.get("turn", 0)

        self._bar_counter += 1
        status = BarStatus.SUCCESS if approved is True else BarStatus.ERROR if approved is False else BarStatus.WARNING

        return TimelineBar(
            id=f"tev-{self._bar_counter}",
            type=BarType.TOOL_CALL,
            label=tool,
            start_time=ts,
            end_time=ts + 0.01,
            duration_ms=10,
            status=status,
            detail={
                "tool": tool,
                "approved": approved,
                "deny_reason": deny_reason,
                "turn": turn,
                "params": entry.get("params", {}),
            },
        )
