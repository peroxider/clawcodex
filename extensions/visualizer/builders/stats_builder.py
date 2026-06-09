"""Operation statistics builder (F-91-C).

Aggregates OperationStats from a list of TimelineBars.
"""

from __future__ import annotations

from ..models.viz_models import BarType, OperationStats, TimelineBar


class StatsBuilder:
    """Build OperationStats from timeline bars."""

    def build(self, bars: list[TimelineBar]) -> OperationStats:
        if not bars:
            return OperationStats()

        total_ops = len(bars)
        by_type: dict[str, int] = {}
        durations: list[int] = []
        max_concurrent = 0

        # Track concurrent bars by time window
        events: list[tuple[float, int]] = []  # (time, delta)
        for bar in bars:
            bar_type = bar.type.value
            by_type[bar_type] = by_type.get(bar_type, 0) + 1
            durations.append(bar.duration_ms)
            events.append((bar.start_time, +1))
            events.append((bar.end_time, -1))

        # Count max concurrent
        events.sort(key=lambda x: (x[0], -x[1]))
        current = 0
        for _, delta in events:
            current += delta
            max_concurrent = max(max_concurrent, current)

        total_duration = sum(durations)
        avg_duration = total_duration / len(durations) if durations else 0.0

        return OperationStats(
            total_ops=total_ops,
            by_type=by_type,
            avg_duration_ms=avg_duration,
            max_concurrent=max_concurrent,
            total_duration_ms=total_duration,
            context_tokens=0,  # populated from snapshot cost block
            cost_usd=0.0,
        )
