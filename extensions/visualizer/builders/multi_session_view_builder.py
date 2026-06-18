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
from datetime import datetime
from typing import Any

from .operation_categorizer import OperationCategorizer
from ..models.viz_models import (
    BarType,
    OperationCategory,
    SessionVizData,
    TimelineBar,
)

logger = logging.getLogger(__name__)


# Tick density — sorted DESCENDING so we pick the LARGEST step that
# still yields <= 8 ticks across the range.  Two layers:
#   _TICK_STEP_MS    sub-second ranges (in milliseconds)
#   _TICK_STEP_SECS  second-and-up ranges (in seconds)
# Matches 0/5/10/15/20/25/30 min in the reference image.
_TICK_STEP_MS: list[int] = [500, 200, 100, 50, 20, 10, 5, 1]
_TICK_STEP_SECS: list[int] = [600, 300, 120, 60, 30, 15, 10, 5, 1]


def _pick_tick_step(total_seconds: float) -> float:
    """Return the largest tick step that yields <= 8 ticks across the range.

    For ranges under 1s we step in milliseconds; for >= 1s we step in seconds.
    """
    if total_seconds < 1.0:
        ms = total_seconds * 1000
        for s in _TICK_STEP_MS:
            if ms / s <= 8:
                return s / 1000  # convert to seconds
        return _TICK_STEP_MS[-1] / 1000
    for s in _TICK_STEP_SECS:
        if total_seconds / s <= 8:
            return s
    return _TICK_STEP_SECS[-1]


def _format_tick(seconds: float) -> str:
    """Format a tick label as ``mm:ss.SSS`` (zero-padded, millisecond precision).

    Examples:
        0       -> '00:00.000'
        30      -> '00:30.000'
        300     -> '05:00.000'
        5400    -> '90:00.000'   (90 min, minute column rolls past 60)
    """
    if seconds is None or seconds < 0:
        seconds = 0
    total_ms = int(round(seconds * 1000))
    minutes, rem_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(rem_ms, 1_000)
    return f"{minutes:02d}:{secs:02d}.{ms:03d}"


def _wall_clock(ts: float) -> str:
    """Format unix timestamp as HH:MM, used for end markers / spawn callouts."""
    if ts <= 0:
        return ""
    import time

    return time.strftime("%H:%M", time.localtime(ts))


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

        # x in seconds, relative to base_time. Do NOT clamp negatives:
        # the start_time backfill in SessionMetadataParser can still be
        # later than a few transcript entries when the agent loop wrote
        # metadata at a wall-clock later than the first message (e.g. an
        # out-of-order resume). Clamping here collapses those bars onto
        # x=0, hiding them off the left edge of the chart. The
        # ``timeRange.min`` below is widened to the actual minimum rel
        # so ECharts renders them in the visible area.
        def rel(t: float) -> float:
            return t - base_time

        categorizer = OperationCategorizer()

        # ---- 1. timeRange
        # Use actual activity range so session end-time drift does not leave
        # a large empty right side.
        max_end: float | None = None
        min_rel: float | None = None
        for s in sessions:
            for bar in s.timeline:
                rel_end = rel(bar.end_time)
                max_end = rel_end if max_end is None else max(max_end, rel_end)
                rel_start = rel(bar.start_time)
                if min_rel is None or rel_start < min_rel:
                    min_rel = rel_start
        if max_end is not None and min_rel is not None:
            if max_end <= min_rel:
                max_end = min_rel + 0.001
        else:
            max_end = 60.0  # fallback for empty timelines (matches old default)
            min_rel = 0.0

        range_min = min(0.0, min_rel)
        total_range = max_end - range_min
        step = _pick_tick_step(total_range)
        # While loop (not range) so sub-second steps work for short
        # in-progress sessions. range() requires int step in Python 3.
        tick_seconds: list[float] = []
        t = range_min
        # Tiny epsilon guards against float drift at fractional step boundaries
        while t <= max_end + 1e-9:
            tick_seconds.append(round(t, 6))
            t += step
        if tick_seconds[-1] < max_end:
            tick_seconds.append(round(max_end, 6))
        tick_labels = [_format_tick(s) for s in tick_seconds]

        # ---- 2. legend (8 categories — full OperationCategory set)
        # F-95 follow-up: previously the legend rolled LLM_TEXT / TURN /
        # BACKGROUND into OTHER (5-pill design-spec). The "其他" bucket
        # was the largest by far in orchestrator sessions (e.g. 30/55 in
        # 9c3ce1e5), with the bulk of it being LLM_TEXT (assistant
        # text/thinking spans). Exposing the 8-category breakdown
        # matches the categorizer's actual resolution and makes the
        # distribution legible — see viz_models.py:OperationCategory
        # for the rationale recorded when the secondary buckets were
        # added in 2026-06-11.
        category_counts: Counter[OperationCategory] = Counter()
        for s in sessions:
            for bar in s.timeline:
                category_counts[categorizer.categorize(bar)] += 1
        _LEGEND_CATEGORIES: list[OperationCategory] = [
            OperationCategory.READ,
            OperationCategory.EXECUTE,
            OperationCategory.WRITE,
            OperationCategory.ORCHESTRATE,
            OperationCategory.LLM_TEXT,
            OperationCategory.TURN,
            OperationCategory.BACKGROUND,
            OperationCategory.OTHER,
        ]
        legend = [
            {
                "category": c.value,
                "label": c.label,
                "color": c.color,
                "count": category_counts.get(c, 0),
            }
            for c in _LEGEND_CATEGORIES
        ]

        # ---- 3. sessions
        session_rows: list[dict[str, Any]] = []
        for y, s in enumerate(sessions):
            ticks = self._build_ticks(s.timeline, rel, categorizer)
            metadata_str = self._session_metadata(s)
            agent_type = self._detect_agent_type(s)
            row: dict[str, Any] = {
                "id": s.session_id,
                "name": self._session_name(s),
                "metadata": metadata_str,
                "agentType": agent_type,
                "y": y,
                "ticks": ticks,
                "status": s.status,
                "model": s.model,
                "totalOps": s.tool_count or s.stats.total_ops,
                "contextTokens": s.stats.context_tokens,
                "contextSize": self._fmt_tokens(s.stats.context_tokens)
                if s.stats.context_tokens
                else "",
                "endMarker": self._end_marker(s, rel),
            }
            summary = s.agent_layout_summary or {}
            if summary.get("spawn_time") is not None:
                spawn_clock = _wall_clock(s.start_time + summary["spawn_time"])
                sub = summary.get("subagent_count", 0)
                row["spawnCallout"] = {
                    "x": summary["spawn_time"],
                    "label": f"▼ {spawn_clock} Workflow 派生 {sub} 子agent"
                    if spawn_clock
                    else f"▼ Workflow 派生 {sub} 子agent",
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
                spawn_x = node.spawn_x or 0.0
                join_x = node.join_x or node.spawn_x or 0.0
                # Extract score from metadata if available (design-spec: 评审/核对评分)
                score = node.metadata.get("score") if node.metadata else None
                score_label = node.metadata.get("score_label") if node.metadata else None
                agent_rows.append(
                    {
                        "id": f"{s.session_id}/{node.agent_id}",
                        "parentSessionId": s.session_id,
                        "name": node.name,
                        "role": node.role or "执行",
                        "roleColor": node.role_color or "#3b82f6",
                        "title": node.name,
                        "count": self._bar_count_for_agent(node),
                        "score": score,
                        "scoreLabel": score_label or node.name,
                        "spawnX": spawn_x,
                        "joinX": join_x,
                        "duration": max(0.001, join_x - spawn_x),
                        "depthY": 0,  # filled in by _renumber_agents
                        "ticks": self._build_agent_ticks(s.timeline, node, rel, categorizer),
                    }
                )
        agent_rows.sort(key=lambda r: (r["parentSessionId"], r["spawnX"]))
        agent_rows = self._renumber_agents(agent_rows, session_rows)

        # ---- 5. edges (fork / join)
        edges = self._build_edges(session_rows, agent_rows)

        return {
            "timeRange": {
                "min": range_min,
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
        # Must match the 8 categories in build()'s _LEGEND_CATEGORIES
        # so empty sessions render the same 8-pill bar as populated ones.
        return [
            {"category": c.value, "label": c.label, "color": c.color, "count": 0}
            for c in [
                OperationCategory.READ,
                OperationCategory.EXECUTE,
                OperationCategory.WRITE,
                OperationCategory.ORCHESTRATE,
                OperationCategory.LLM_TEXT,
                OperationCategory.TURN,
                OperationCategory.BACKGROUND,
                OperationCategory.OTHER,
            ]
        ]

    def _session_name(self, s: SessionVizData) -> str:
        """Compose the model pill label, e.g. ``Opus4.8 · xhigh``.

        Fallback chain (avoids the meaningless literal ``"session"`` when
        the metadata has no model and no detected mode — e.g. an
        orchestrator session where ``metadata.json`` only has
        ``session_id`` and ``start_time``):

            1. ``<model> · <mode>``  when model is set
            2. ``<mode>``            when mode is set
            3. ``<session_id[:8]>``  short id
        """
        model = (s.model or "").strip()
        for prefix in ("claude-", "openai-", "azure-"):
            if model.lower().startswith(prefix):
                model = model[len(prefix) :]
                break
        mode = (s.detected_mode or s.config_summary.get("config") or "").strip()
        if model and mode:
            return f"{model} · {mode}"
        if model:
            return model
        if mode:
            return mode
        # Last-resort: short id (e.g. "run-01-2") instead of literal "session"
        return s.session_id[:8] or "session"

    def _build_ticks(
        self,
        timeline: list[TimelineBar],
        rel_fn,
        categorizer: OperationCategorizer,
    ) -> list[dict[str, Any]]:
        """Project timeline bars into dense x positions for the activity-bar view."""
        ticks: list[dict[str, Any]] = []
        for bar in timeline:
            if bar.end_time <= 0:
                continue
            cat = categorizer.categorize(bar)
            ticks.append(
                {
                    "x": rel_fn(bar.start_time),
                    "w": max(0.001, rel_fn(bar.end_time) - rel_fn(bar.start_time)),
                    "category": cat.value,
                    "color": bar.color or cat.color,
                    "status": bar.status.value if hasattr(bar.status, "value") else str(bar.status),
                    "label": bar.label,
                    "id": bar.id,
                    "type": bar.type.value if hasattr(bar.type, "value") else str(bar.type),
                    "detail": bar.detail,
                    "toolUseId": bar.detail.get("tool_use_id")
                    if isinstance(bar.detail, dict)
                    else "",
                    # Bezier-view extension: ISO-8601 absolute timestamp for
                    # the EventDetailPanel. Computed here (not stored on the
                    # bar) so the parser stays free of presentation concerns.
                    # ``bar.absolute_time`` takes precedence when the parser
                    # has already filled it (e.g. tests injecting pre-stamped
                    # bars), otherwise we derive from start_time. None when
                    # the bar has no parseable timestamp.
                    "absoluteTime": (
                        bar.absolute_time
                        if bar.absolute_time
                        else (
                            datetime.fromtimestamp(bar.start_time).isoformat()
                            if bar.start_time > 0
                            else None
                        )
                    ),
                    "durationUnrecorded": bar.duration_unrecorded,
                    "durationHeuristic": bar.duration_heuristic,
                    "tsUnrecorded": bar.ts_unrecorded,
                    "model": bar.model,
                    "userRole": bar.user_role,
                    "userText": bar.user_text,
                    "systemText": bar.system_text,
                }
            )
        return ticks

    def _build_agent_ticks(
        self,
        timeline: list[TimelineBar],
        node,
        rel_fn,
        categorizer: OperationCategorizer,
    ) -> list[dict[str, Any]]:
        """Project activity into a sub-agent lane.

        Prefer bars that explicitly carry the child ``agent_id``.  Real
        transcripts often do not have that ownership yet, so fall back to
        the node's spawn/join window and render non-orchestration activity
        in that interval as the sub-agent's activity fingerprint.
        """
        spawn_x = node.spawn_x
        join_x = node.join_x
        if spawn_x is None:
            return []
        if join_x is None or join_x <= spawn_x:
            join_x = spawn_x + 0.001

        explicit: list[TimelineBar] = []
        for bar in timeline:
            detail = bar.detail or {}
            owner = bar.agent_id or detail.get("agent_id") or detail.get("subagent_id")
            if owner and str(owner) == str(node.agent_id):
                explicit.append(bar)
        source = (
            explicit
            if explicit
            else [
                bar
                for bar in timeline
                if spawn_x <= rel_fn(bar.start_time) <= join_x
                and categorizer.categorize(bar) != OperationCategory.ORCHESTRATE
            ]
        )

        ticks: list[dict[str, Any]] = []
        for bar in source:
            if bar.end_time <= 0:
                continue
            cat = categorizer.categorize(bar)
            x = rel_fn(bar.start_time)
            end = rel_fn(bar.end_time)
            ticks.append(
                {
                    "x": x,
                    "w": max(0.001, end - x),
                    "category": cat.value,
                    "color": bar.color or cat.color,
                    "status": bar.status.value if hasattr(bar.status, "value") else str(bar.status),
                    "label": bar.label,
                    "id": f"{node.agent_id}:{bar.id}",
                    "type": bar.type.value if hasattr(bar.type, "value") else str(bar.type),
                    "detail": bar.detail,
                    "toolUseId": bar.detail.get("tool_use_id")
                    if isinstance(bar.detail, dict)
                    else "",
                    "absoluteTime": (
                        bar.absolute_time
                        if bar.absolute_time
                        else (
                            datetime.fromtimestamp(bar.start_time).isoformat()
                            if bar.start_time > 0
                            else None
                        )
                    ),
                    "durationUnrecorded": bar.duration_unrecorded,
                    "durationHeuristic": bar.duration_heuristic,
                    "tsUnrecorded": bar.ts_unrecorded,
                    "model": bar.model,
                    "userRole": bar.user_role,
                    "userText": bar.user_text,
                    "systemText": bar.system_text,
                }
            )
        return ticks

    def _session_metadata(self, s: SessionVizData) -> str:
        """Compose the human-readable stats line, e.g.
        ``53 工具调用 · 单agent · 上下文 138K`` or
        ``61 主线 + 22 子agent (328 调用) · 主agent上下文 164K · 子agent 21-66K``.
        """
        parts: list[str] = []
        tool_count = s.tool_count
        if not tool_count:
            # Count every TOOL_CALL bar in the parent swimlane.
            tool_count = sum(
                1
                for b in s.timeline
                if b.type == BarType.TOOL_CALL and b.category != OperationCategory.ORCHESTRATE
            )
        sub = s.agent_layout_summary.get("subagent_count", 0) if s.agent_layout_summary else 0
        if tool_count and sub:
            # Subagent call counts (sum of agent_trees stats.total_ops)
            sub_calls = sum(n.stats.total_ops for n in s.agent_tree if n.parent_id and n.stats) or (
                tool_count * sub
            )  # rough estimate
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

        # Sub-agent context range (for multi-agent sessions)
        if sub:
            sub_ctxs = [
                n.stats.context_tokens
                for n in s.agent_tree
                if n.parent_id and n.stats and n.stats.context_tokens
            ]
            if sub_ctxs:
                min_ctx = min(sub_ctxs)
                max_ctx = max(sub_ctxs)
                if min_ctx == max_ctx:
                    parts.append(f"子agent {self._fmt_tokens(min_ctx)}")
                else:
                    parts.append(f"子agent {self._fmt_tokens(min_ctx)}-{self._fmt_tokens(max_ctx)}")

        text = " · ".join(parts) if parts else "—"
        # F-95 follow-up: truncate long metadata so it doesn't overflow
        # the chart canvas / y-axis gutter when sessions have a lot of
        # sub-agents and large context windows.
        if len(text) > 80:
            text = text[:79] + "…"
        return text

    def _end_marker(self, s: SessionVizData, rel_fn) -> dict[str, Any] | None:
        end = s.end_time
        if not end:
            return None
        x = rel_fn(end)
        clock = _wall_clock(end)
        sub = s.agent_layout_summary.get("subagent_count", 0) if s.agent_layout_summary else 0
        if sub:
            status_label = "汇合修复 ✓"
        elif s.status in ("success", "completed"):
            status_label = "收工 ✓"
        elif s.status in ("failed", "error"):
            status_label = "失败 ✗"
        elif s.status == "running":
            status_label = "进行中"
        else:
            status_label = "结束"
        # Design-spec: single-agent mode label
        if s.detected_mode == "single" and not sub:
            status_label = f"单agent{status_label}"
        label = f"{clock} {status_label}" if clock else status_label
        return {
            "x": x,
            "label": label,
            "timeLabel": clock or "",
            "statusLabel": status_label,
        }

    def _detect_agent_type(self, s: SessionVizData) -> str:
        """Detect agent type description for the design-spec model pill right-side info."""
        sub = s.agent_layout_summary.get("subagent_count", 0) if s.agent_layout_summary else 0
        if s.detected_mode == "single" and not sub:
            return "单agent"
        if sub:
            return f"xhigh+workflows"
        return s.detected_mode or "agent"

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
                children,
                parent=node.agent_id,
                session_id=session_id,
                base_y=base_y,
                row_offset=y,
                out=out,
                rel_fn=rel_fn,
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
                edges.append(
                    {
                        "type": "fork",
                        "from": {"x": a["spawnX"], "y": parent_y},
                        "to": {"x": a["spawnX"], "y": a["depthY"]},
                        "color": "#ea7ccc",
                    }
                )
            if a.get("joinX") is not None and a["joinX"] != a.get("spawnX"):
                edges.append(
                    {
                        "type": "join",
                        "from": {"x": a["joinX"], "y": a["depthY"]},
                        "to": {"x": a["joinX"], "y": parent_y},
                        "color": "#ea7ccc",
                    }
                )
        return edges

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1024 * 1024:
            return f"{n / (1024 * 1024):.1f}M"
        if n >= 1024:
            return f"{n // 1024}K"
        return str(n)


__all__ = ["MultiSessionViewBuilder"]
