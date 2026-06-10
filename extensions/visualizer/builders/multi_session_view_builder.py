"""Multi-session waterfall view builder (F-95).

Assembles the JSON payload consumed by ``multi_session_view.js`` from
1-5 ``SessionVizData`` instances.  The output schema is the contract
that the frontend custom-series chart binds to.

Top-level shape::

    {
      "timeRange":  {"min": float, "max": float, "tickSeconds": [...], "tickLabels": [...]},
      "legend":     [{"category": str, "label": str, "color": str, "count": int}, ...],
      "sessions":   [SessionRow, ...],
      "agents":     [AgentRow, ...],
      "edges":      [Edge, ...]
    }

Time alignment: all x-coordinates are *relative* to the earliest
``start_time`` across the supplied sessions, so multiple sessions line
up on a shared axis (matches the reference image where multiple rows
share the same 0-30 min scale).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from ..models.viz_models import (
    BarType,
    OperationCategory,
    SessionVizData,
    TimelineBar,
)

logger = logging.getLogger(__name__)


# Tick density (seconds per major tick) — matches 0/5/10/15/20/25/30 min
# in the reference image.  Sorted DESCENDING so we pick the LARGEST step
# that still yields <= 8 ticks across the range.
_TICK_STEP_SECONDS: list[int] = [600, 300, 120, 60, 30, 15, 10, 5, 1]


def _pick_tick_step(total_seconds: float) -> int:
    for s in _TICK_STEP_SECONDS:
        # 6-7 ticks across the range
        if total_seconds / s <= 8:
            return s
    return _TICK_STEP_SECONDS[-1]


def _format_tick(seconds: float) -> str:
    """Format a tick label in minutes (e.g. '5分钟')."""
    if seconds == 0:
        return "0分钟"
    minutes = seconds / 60
    if minutes < 1:
        return f"{int(seconds)}s"
    if minutes == int(minutes):
        return f"{int(minutes)}分钟"
    return f"{minutes:.1f}分钟"


def _wall_clock(ts: float) -> str:
    """Format unix timestamp as HH:MM, used for end markers / spawn callouts."""
    if ts <= 0:
        return ""
    import time
    return time.strftime("%H:%M", time.localtime(ts))


def _classify_ticks(bar: TimelineBar) -> OperationCategory:
    """Get the bar's category, with safe fallback."""
    if bar.category is not None:
        return bar.category
    return OperationCategory.OTHER


class MultiSessionViewBuilder:
    """Build the multi-session waterfall view payload."""

    def build(self, sessions: list[SessionVizData]) -> dict[str, Any]:
        if not sessions:
            return {
                "timeRange": {"min": 0, "max": 0, "tickSeconds": [], "tickLabels": []},
                "legend": self._empty_legend(),
                "sessions": [],
                "agents": [],
                "edges": [],
            }

        base_time = min(s.start_time or 0 for s in sessions)
        # x in seconds, relative to base_time
        def rel(t: float) -> float:
            return max(0.0, t - base_time)

        # ---- 1. timeRange
        max_end = 0.0
        for s in sessions:
            if s.end_time and s.end_time > base_time:
                max_end = max(max_end, rel(s.end_time))
            for bar in s.timeline:
                max_end = max(max_end, rel(bar.end_time))
            for node in s.agent_tree:
                if node.spawn_x is not None:
                    max_end = max(max_end, node.spawn_x)
                if node.join_x is not None:
                    max_end = max(max_end, node.join_x)
        max_end = max(max_end, 60.0)  # at least 1 minute of axis

        step = _pick_tick_step(max_end)
        tick_seconds = list(range(0, int(max_end) + 1, step))
        if tick_seconds[-1] < max_end:
            tick_seconds.append(int(max_end))
        tick_labels = [_format_tick(s) for s in tick_seconds]

        # ---- 2. legend
        category_counts: Counter[OperationCategory] = Counter()
        for s in sessions:
            for bar in s.timeline:
                if bar.category is not None:
                    category_counts[bar.category] += 1
                else:
                    category_counts[OperationCategory.OTHER] += 1
        legend = [
            {
                "category": c.value,
                "label": c.label,
                "color": c.color,
                "count": category_counts.get(c, 0),
            }
            for c in OperationCategory
        ]

        # ---- 3. sessions
        session_rows: list[dict[str, Any]] = []
        for y, s in enumerate(sessions):
            ticks = self._build_ticks(s.timeline, rel)
            row: dict[str, Any] = {
                "id": s.session_id,
                "name": self._session_name(s),
                "metadata": self._session_metadata(s),
                "y": y,
                "ticks": ticks,
                "status": s.status,
                "model": s.model,
                "endMarker": self._end_marker(s, rel),
            }
            summary = s.agent_layout_summary or {}
            if summary.get("spawn_time") is not None:
                spawn_clock = _wall_clock(s.start_time + summary["spawn_time"])
                sub = summary.get("subagent_count", 0)
                row["spawnCallout"] = {
                    "x": summary["spawn_time"],
                    "label": f"{spawn_clock}  Workflow 派生 {sub} 子agent" if spawn_clock else f"Workflow 派生 {sub} 子agent",
                    "subagentCount": sub,
                    "byRole": summary.get("by_role", {}),
                }
            session_rows.append(row)

        # ---- 4. agents (cascade under their parent session row)
        # P0 simplified: agent_tree is a flat list with parent_id refs.
        # Skip root nodes (parent_id is None or "") — they are rendered
        # as session rows, not as agent rows. Order by spawn_x to get
        # visual stability across renders.
        agent_rows: list[dict[str, Any]] = []
        for s in sessions:
            for node in s.agent_tree:
                if not node.parent_id:  # None or ""
                    continue
                agent_rows.append({
                    "id": f"{s.session_id}/{node.agent_id}",
                    "parentSessionId": s.session_id,
                    "name": node.name,
                    "role": node.role or "执行",
                    "roleColor": node.role_color or "#a0a0b0",
                    "title": node.name,
                    "count": self._bar_count_for_agent(node),
                    "spawnX": node.spawn_x or 0.0,
                    "joinX": node.join_x or node.spawn_x or 0.0,
                    "depthY": 0,  # filled in by _renumber_agents
                    "ticks": [],
                })
        agent_rows.sort(key=lambda r: (r["parentSessionId"], r["spawnX"]))
        agent_rows = self._renumber_agents(agent_rows, session_rows)

        # ---- 5. edges (fork / join)
        edges = self._build_edges(session_rows, agent_rows)

        return {
            "timeRange": {
                "min": 0.0,
                "max": max_end,
                "tickSeconds": tick_seconds,
                "tickLabels": tick_labels,
            },
            "legend": legend,
            "sessions": session_rows,
            "agents": agent_rows,
            "edges": edges,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _empty_legend(self) -> list[dict[str, Any]]:
        return [
            {"category": c.value, "label": c.label, "color": c.color, "count": 0}
            for c in OperationCategory
        ]

    def _session_name(self, s: SessionVizData) -> str:
        """Compose the model pill label, e.g. ``Opus4.8 · xhigh``."""
        model = (s.model or "").strip()
        # Strip a long provider prefix like "claude-" for readability
        for prefix in ("claude-", "openai-", "azure-"):
            if model.lower().startswith(prefix):
                model = model[len(prefix):]
                break
        # Take just the family identifier (e.g. opus-4-7)
        mode = (s.detected_mode or s.config_summary.get("config") or "session")
        if model:
            return f"{model} · {mode}"
        return mode or s.session_id[:8]

    def _build_ticks(
        self,
        timeline: list[TimelineBar],
        rel_fn,
    ) -> list[dict[str, Any]]:
        """Project timeline bars into dense x positions for the activity-bar view."""
        ticks: list[dict[str, Any]] = []
        for bar in timeline:
            if bar.end_time <= 0:
                continue
            cat = _classify_ticks(bar)
            ticks.append({
                "x": rel_fn(bar.start_time),
                "w": max(0.05, rel_fn(bar.end_time) - rel_fn(bar.start_time)),
                "category": cat.value,
                "color": bar.color or cat.color,
                "status": bar.status.value if hasattr(bar.status, "value") else str(bar.status),
                "label": bar.label,
                "id": bar.id,
            })
        return ticks

    def _session_metadata(self, s: SessionVizData) -> str:
        """Compose the human-readable stats line, e.g.
        ``61 主线 + 22 子agent (328 调用) · 主agent上下文 164K · 子agent 21-66K``.
        """
        parts: list[str] = []
        tool_count = s.tool_count
        if not tool_count:
            # Count every TOOL_CALL bar in the parent swimlane.
            tool_count = sum(
                1 for b in s.timeline
                if b.type == BarType.TOOL_CALL and b.category != OperationCategory.ORCHESTRATE
            )
        sub = s.agent_layout_summary.get("subagent_count", 0) if s.agent_layout_summary else 0
        if tool_count and sub:
            # Subagent call counts (sum of agent_trees stats.total_ops)
            sub_calls = sum(
                n.stats.total_ops for n in s.agent_tree
                if n.parent_id and n.stats
            ) or (tool_count * sub)  # rough estimate
            parts.append(f"{tool_count} 主线 + {sub} 子agent ({sub_calls} 调用)")
        elif tool_count:
            parts.append(f"{tool_count} 工具调用")
        elif sub:
            parts.append(f"{sub} 子agent")

        # Agent mode hint
        if s.detected_mode == "single" and not sub:
            parts.append("单agent")

        # Context tokens
        ctx = s.stats.context_tokens
        if ctx:
            parts.append(f"上下文 {self._fmt_tokens(ctx)}")
        return " · ".join(parts) if parts else "—"

    def _end_marker(self, s: SessionVizData, rel_fn) -> dict[str, Any] | None:
        end = s.end_time
        if not end:
            return None
        x = rel_fn(end)
        clock = _wall_clock(end)
        if s.status in ("success", "completed"):
            label = f"{clock} 收工 ✓"
        elif s.status in ("failed", "error"):
            label = f"{clock} 失败 ✗"
        elif s.status == "running":
            label = f"{clock} 进行中"
        elif sub := s.agent_layout_summary.get("subagent_count", 0) if s.agent_layout_summary else 0:
            label = f"{clock} 汇合修复 ✓"
        else:
            label = f"{clock} 结束"
        return {"x": x, "label": label}

    def _flatten_agents(
        self,
        children: dict[str | None, list],
        parent: str | None,
        session_id: str,
        base_y: int,
        row_offset: int,
        out: list[dict[str, Any]],
        rel_fn,
    ) -> int:
        """Kept for backward compatibility — no-op in P0 simplified view.

        Modern caller (see ``build``) iterates non-root nodes directly.
        This stub remains so any external caller of the old signature
        doesn't break; it just walks children and emits rows.
        """
        kids = children.get(parent, []) if parent else []
        y = row_offset
        for node in kids:
            if not node.parent_id:  # skip roots
                continue
            row = {
                "id": f"{session_id}/{node.agent_id}",
                "parentSessionId": session_id,
                "name": node.name,
                "role": node.role or "执行",
                "roleColor": node.role_color or "#a0a0b0",
                "title": node.name,
                "count": self._bar_count_for_agent(node),
                "spawnX": node.spawn_x or 0.0,
                "joinX": node.join_x or node.spawn_x or 0.0,
                "depthY": y,
                "ticks": [],
            }
            out.append(row)
            y += 1
            y = self._flatten_agents(
                children, parent=node.agent_id, session_id=session_id,
                base_y=base_y, row_offset=y, out=out, rel_fn=rel_fn,
            )
        return y

    def _renumber_agents(
        self,
        agent_rows: list[dict[str, Any]],
        session_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Re-pack depth_y so each session's sub-agents are stacked right below it."""
        if not agent_rows:
            return agent_rows
        session_y = {r["id"]: r["y"] for r in session_rows}
        per_session: dict[str, list[dict[str, Any]]] = {}
        for r in agent_rows:
            per_session.setdefault(r["parentSessionId"], []).append(r)
        new_rows: list[dict[str, Any]] = []
        for sid, rows in per_session.items():
            base = session_y.get(sid, 0) + 1
            for i, r in enumerate(rows):
                r["depthY"] = base + i
                new_rows.append(r)
        return new_rows

    @staticmethod
    def _bar_count_for_agent(node) -> int:
        """Pull a tool-call count from node.stats or metadata if present."""
        stats = node.stats
        if stats and stats.total_ops:
            return stats.total_ops
        meta = node.metadata or {}
        return int(meta.get("call_count") or meta.get("tool_count") or 0)

    def _build_edges(
        self,
        session_rows: list[dict[str, Any]],
        agent_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for a in agent_rows:
            parent_y = next(
                (s["y"] for s in session_rows if s["id"] == a["parentSessionId"]),
                0,
            )
            if a.get("spawnX") is not None:
                edges.append({
                    "type": "fork",
                    "from": {"x": a["spawnX"], "y": parent_y},
                    "to": {"x": a["spawnX"], "y": a["depthY"]},
                    "color": "#ea7ccc",
                })
            if a.get("joinX") is not None and a["joinX"] != a.get("spawnX"):
                edges.append({
                    "type": "join",
                    "from": {"x": a["joinX"], "y": a["depthY"]},
                    "to": {"x": a["joinX"], "y": parent_y},
                    "color": "#ea7ccc",
                })
        return edges

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1024 * 1024:
            return f"{n / (1024 * 1024):.1f}M"
        if n >= 1024:
            return f"{n // 1024}K"
        return str(n)


__all__ = ["MultiSessionViewBuilder"]
