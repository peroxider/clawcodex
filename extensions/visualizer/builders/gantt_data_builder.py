"""Gantt chart data builder (F-91-C).

Assembles TimelineBar objects into ECharts-compatible gantt data format.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models.viz_models import BarStatus, BarType, SessionVizData, TimelineBar, TimeMode

logger = logging.getLogger(__name__)


class GanttDataBuilder:
    """Build ECharts custom-series gantt data from TimelineBars."""

    # Default color palette for bar types
    _TYPE_COLORS: dict[BarType, str] = {
        BarType.LLM_CALL: "#5470c6",
        BarType.TOOL_CALL: "#91cc75",
        BarType.TOOL_RESULT: "#fac858",
        BarType.PHASE: "#ee6666",
        BarType.TURN: "#73c0de",
        BarType.SESSION: "#3ba272",
        BarType.WAIT: "#fc8452",
        BarType.CUSTOM: "#9a60b4",
    }

    def __init__(self, time_mode: TimeMode = TimeMode.RELATIVE) -> None:
        self.time_mode = time_mode

    def build(self, session: SessionVizData) -> dict[str, Any]:
        """Build complete gantt payload for ECharts."""
        bars = list(session.timeline)
        if not bars:
            return {
                "categories": [],
                "series": [],
                "timeRange": {"min": 0, "max": 0},
            }

        # Negative-length bars are clearly corrupt data; drop them and warn.
        # We deliberately KEEP zero-length bars (end_time == start_time) here:
        # the transcript parser creates them as "pending" placeholders that
        # get updated when the matching result event arrives. The renderer
        # (gantt.js) clamps zero-width bars to a 2px minimum, so they remain
        # visible without inflating the xAxis range — and we don't silently
        # lose tools that never got a result (truncated/crashed sessions).
        kept = [b for b in bars if b.end_time >= b.start_time]
        negative = [b for b in bars if b.end_time < b.start_time]
        if negative:
            logger.warning(
                "gantt: dropped %d negative-length bars (end<start) for session %s",
                len(negative),
                session.session_id,
            )
        bars = kept
        if not bars:
            return {
                "categories": [],
                "series": [],
                "timeRange": {"min": 0, "max": 0},
            }

        # If an unusually large fraction of bars are zero-length, log a
        # diagnostic so the team can investigate the upstream data quality.
        if bars:
            zero_count = sum(1 for b in bars if b.end_time == b.start_time)
            if zero_count / len(bars) > 0.5 and len(bars) > 5:
                logger.info(
                    "gantt: session %s has %d/%d zero-length bars (likely "
                    "pending placeholders or stalled data feed)",
                    session.session_id,
                    zero_count,
                    len(bars),
                )

        # Compute time offset
        base_time = bars[0].start_time if self.time_mode == TimeMode.RELATIVE else 0.0

        # Build categories (y-axis rows) by grouping
        categories = self._build_categories(bars)
        category_map = {cat: idx for idx, cat in enumerate(categories)}

        # Build series data
        series_data: list[list[Any]] = []
        for bar in bars:
            cat_idx = category_map.get(self._category_for_bar(bar), 0)
            start = (
                bar.start_time - base_time
                if self.time_mode == TimeMode.RELATIVE
                else bar.start_time
            )
            end = bar.end_time - base_time if self.time_mode == TimeMode.RELATIVE else bar.end_time

            color = bar.color or self._color_for_bar(bar)
            series_data.append(
                [
                    cat_idx,
                    round(start * 1000),  # ms for ECharts
                    round(end * 1000),
                    bar.duration_ms,
                    bar.label,
                    bar.id,
                    bar.status.value,
                    color,
                    bar.detail,
                    bar.type.value,
                ]
            )

        # Default Gantt bounds follow the actual visible bars. Session
        # metadata can extend long after the final agent/tool event, which
        # creates large empty space on the right and makes short bars hard to
        # select.
        bar_min = min(b.start_time for b in bars) - base_time
        bar_max = max(b.end_time for b in bars) - base_time

        min_time = bar_min
        max_time = bar_max

        # Give all-zero-length timelines a tiny range so ECharts can render.
        if max_time <= min_time:
            max_time = min_time + 0.001

        return {
            "categories": categories,
            "series": series_data,
            "timeRange": {
                "min": round(min_time * 1000),
                "max": round(max_time * 1000),
            },
            "timeMode": self.time_mode.value,
            "sessionId": session.session_id,
        }

    def _build_categories(self, bars: list[TimelineBar]) -> list[str]:
        """Group bars into y-axis categories."""
        seen: set[str] = set()
        categories: list[str] = []
        for bar in bars:
            cat = self._category_for_bar(bar)
            if cat not in seen:
                seen.add(cat)
                categories.append(cat)
        return categories

    def _category_for_bar(self, bar: TimelineBar) -> str:
        """Determine category for a bar."""
        if bar.group_id:
            return bar.group_id
        if bar.agent_id:
            return bar.agent_id
        return bar.type.value

    def _color_for_bar(self, bar: TimelineBar) -> str:
        """Determine color for a bar."""
        if bar.color:
            return bar.color
        return self._TYPE_COLORS.get(bar.type, "#9a60b4")
