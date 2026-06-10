"""Operation statistics builder (F-91-C).

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

        # Carry forward fields that can't be derived from the timeline.
        context_tokens = base.context_tokens if base is not None else 0
        cost_usd = base.cost_usd if base is not None else 0.0

        return OperationStats(
            total_ops=total_ops,
            by_type=by_type,
            avg_duration_ms=avg_duration,
            max_concurrent=max_concurrent,
            total_duration_ms=total_duration,
            context_tokens=context_tokens,
            cost_usd=cost_usd,
        )
