"""Cross-session comparison builder (F-91-C).

Compares metrics across multiple sessions.
"""

from __future__ import annotations

from typing import Any

from ..models.viz_models import BarStatus, ComparisonResult, OperationStats, SessionVizData


class ComparisonBuilder:
    """Build cross-session comparison data."""

    def build(self, sessions: list[SessionVizData]) -> ComparisonResult:
        if not sessions:
            return ComparisonResult()

        session_ids = [s.session_id for s in sessions]
        per_session: dict[str, OperationStats] = {}

        for s in sessions:
            per_session[s.session_id] = s.stats

        # Common metrics
        total_cost = sum(s.stats.cost_usd for s in sessions)
        total_duration = sum(s.duration_ms for s in sessions)
        total_turns = sum(s.turn_count for s in sessions)
        total_tools = sum(s.tool_count for s in sessions)

        common_metrics: dict[str, Any] = {
            "session_count": len(sessions),
            "total_cost_usd": round(total_cost, 4),
            "total_duration_ms": total_duration,
            "total_turns": total_turns,
            "total_tools": total_tools,
            "avg_duration_ms": round(total_duration / len(sessions), 1) if sessions else 0,
            "avg_turns": round(total_turns / len(sessions), 1) if sessions else 0,
            "success_rate": self._success_rate(sessions),
        }

        # Delta (max vs min)
        durations = [s.duration_ms for s in sessions]
        costs = [s.stats.cost_usd for s in sessions]
        delta: dict[str, Any] = {}
        if len(durations) > 1:
            delta = {
                "max_duration_ms": max(durations),
                "min_duration_ms": min(durations),
                "max_cost_usd": max(costs) if costs else 0,
                "min_cost_usd": min(costs) if costs else 0,
                "duration_spread_ms": max(durations) - min(durations),
                "cost_spread_usd": round(max(costs) - min(costs), 4) if costs else 0,
            }

        return ComparisonResult(
            sessions=session_ids,
            common_metrics=common_metrics,
            per_session=per_session,
            delta=delta,
        )

    def _success_rate(self, sessions: list[SessionVizData]) -> float:
        if not sessions:
            return 0.0
        success_count = sum(1 for s in sessions if s.status == "success" or s.status == "completed")
        return round(success_count / len(sessions) * 100, 1)
