"""Gantt chart data builder (F-91-C).

Assembles TimelineBar objects into ECharts-compatible gantt data format.
"""

from __future__ import annotations

from typing import Any

from ..models.viz_models import BarStatus, BarType, SessionVizData, TimelineBar, TimeMode


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
        bars = session.timeline
        if not bars:
            return {
                "categories": [],
                "series": [],
                "timeRange": {"min": 0, "max": 0},
            }

        # Compute time offset
        base_time = bars[0].start_time if self.time_mode == TimeMode.RELATIVE else 0.0

        # Build categories (y-axis rows) by grouping
        categories = self._build_categories(bars)
        category_map = {cat: idx for idx, cat in enumerate(categories)}

        # Build series data
        series_data: list[list[Any]] = []
        for bar in bars:
            cat_idx = category_map.get(self._category_for_bar(bar), 0)
            start = bar.start_time - base_time if self.time_mode == TimeMode.RELATIVE else bar.start_time
            end = bar.end_time - base_time if self.time_mode == TimeMode.RELATIVE else bar.end_time

            color = bar.color or self._color_for_bar(bar)
            series_data.append([
                cat_idx,
                round(start * 1000),  # ms for ECharts
                round(end * 1000),
                bar.duration_ms,
                bar.label,
                bar.id,
                bar.status.value,
                color,
                bar.detail,
            ])

        min_time = min(b.start_time for b in bars) - base_time if self.time_mode == TimeMode.RELATIVE else min(b.start_time for b in bars)
        max_time = max(b.end_time for b in bars) - base_time if self.time_mode == TimeMode.RELATIVE else max(b.end_time for b in bars)

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
