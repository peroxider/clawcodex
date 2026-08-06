"""Operation statistics builder.

Aggregates OperationStats from a list of TimelineBars.
"""

from __future__ import annotations

from ..models.viz_models import BarType, OperationStats, TimelineBar


class StatsBuilder:
    """Build OperationStats from timeline bars."""

    def build(
        self,
        bars: list[TimelineBar],
        base: OperationStats | None = None,
    ) -> OperationStats:
        """Build stats from bars, optionally preserving fields from ``base``.

        ``base`` lets callers carry forward values that aren't derivable
        from the timeline itself — most importantly ``cost_usd`` and
        ``context_tokens`` populated from session snapshots / metadata
        by the upstream parser. Without this, ``timeline_builder`` would
        wipe out the enrichment as soon as it recomputes stats.
        """
        if not bars:
            # Nothing to aggregate, but still preserve enrichment from base.
            if base is not None:
                return OperationStats(
                    total_ops=0,
                    by_type={},
                    avg_duration_ms=0.0,
                    max_concurrent=0,
                    total_duration_ms=0,
                    wall_clock_duration_ms=0,
                    context_tokens=base.context_tokens,
                    cost_usd=base.cost_usd,
                )
            return OperationStats()

        total_ops = len(bars)
        by_type: dict[str, int] = {}
        durations: list[int] = []
        max_concurrent = 0

        # Track concurrent bars by time window
        events: list[tuple[float, int]] = []  # (time, delta)
        # Track wall-clock span — note this can be < total_duration_ms
        # when bars overlap, and can diverge from total_duration_ms when
        # bar ``duration_ms`` values are parser approximations rather
        # than true wall-clock deltas.
        wall_start: float | None = None
        wall_end: float | None = None
        for bar in bars:
            bar_type = bar.type.value
            by_type[bar_type] = by_type.get(bar_type, 0) + 1
            durations.append(bar.duration_ms)
            events.append((bar.start_time, +1))
            events.append((bar.end_time, -1))
            if wall_start is None or bar.start_time < wall_start:
                wall_start = bar.start_time
            if wall_end is None or bar.end_time > wall_end:
                wall_end = bar.end_time

        # Count max concurrent
        events.sort(key=lambda x: (x[0], -x[1]))
        current = 0
        for _, delta in events:
            current += delta
            max_concurrent = max(max_concurrent, current)

        total_duration = sum(durations)
        avg_duration = total_duration / len(durations) if durations else 0.0
        wall_clock_duration = (
            int((wall_end - wall_start) * 1000)
            if wall_start is not None and wall_end is not None and wall_end >= wall_start
            else 0
        )

        # Carry forward fields that can't be derived from the timeline.
        context_tokens = base.context_tokens if base is not None else 0
        cost_usd = base.cost_usd if base is not None else 0.0

        return OperationStats(
            total_ops=total_ops,
            by_type=by_type,
            avg_duration_ms=avg_duration,
            max_concurrent=max_concurrent,
            total_duration_ms=total_duration,
            wall_clock_duration_ms=wall_clock_duration,
            context_tokens=context_tokens,
            cost_usd=cost_usd,
        )
