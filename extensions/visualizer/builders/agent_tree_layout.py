"""Multi-agent tree layout (F-95 waterfall rows).

Infers the spawn / join x-coordinates and y-row (depth_y) for every
sub-agent in ``SessionVizData.agent_tree``, by mining the parent agent's
timeline for ``Agent`` / ``Task`` invocations.

Algorithm (single-pass, no recursion):
  1. Walk ``session.timeline`` and pick out bars that represent
     subagent invocations — match by any of:
       a) ``detail.isAgentInvocation`` / ``is_agent_invocation`` truthy
       b) ``detail.subagent_type`` / ``subagent_description`` present
       c) ``bar.label`` in ``{"Agent", "Task"}`` and category == ORCHESTRATE
     Each match becomes a *spawn event* with a relative-time x.
  2. For each spawn event, look up the matching AgentTreeNode:
       - exact match on ``agent_id`` if detail has it
       - else match on (subagent_type, subagent_description) tuple
       - else fall back to the first unconsumed child of the parent
     Set ``spawn_x = event.x`` and ``depth_y = next free y (1..N)``.
  3. ``join_x`` = end_time of the last tool_call bar in the same parent
     branch after the spawn. Approximation: last bar of session.timeline
     with start_time >= spawn_x. If none, fall back to the spawn_x.
  4. Compute a summary into ``session.agent_layout_summary``:
       - ``spawn_time`` / ``join_time``: earliest spawn_x / latest join_x
       - ``subagent_count``
       - ``by_role``: Counter of sub-agent role labels

Auto-promotion fallback: if ``agent_tree`` is empty but the timeline
contains Agent calls, we synthesize one ``AgentTreeNode`` per unique
``(subagent_type, subagent_description)`` so the layout has rows to draw.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from ..models.viz_models import (
    AgentTreeNode,
    BarStatus,
    BarType,
    OperationCategory,
    SessionVizData,
    TimelineBar,
)

logger = logging.getLogger(__name__)

# Map of subagent_type (or description) → display role label
_ROLE_LABELS: dict[str, str] = {
    "review": "评审",
    "verify": "核对",
    "edit": "写入",
    "test": "核对",
    "default": "执行",
}


def _role_label_for(subagent_type: str | None, description: str | None) -> str:
    """Map a subagent_type / description to the Chinese role pill label."""
    key = (subagent_type or description or "").lower()
    for k, label in _ROLE_LABELS.items():
        if k in key:
            return label
    # Heuristic: anything mentioning 'verify' / 'check' / 'audit' → 核对
    text = (description or "").lower()
    if any(t in text for t in ("审", "核", "验", "check", "verify", "audit", "test")):
        return "核对"
    return "执行"


def _role_color_for(role: str) -> str:
    """Role pill color — aligned with design-spec reference image.

    评审(purple) / 核对(red) / 写入(pink) / 执行(blue)
    """
    return {
        "评审": "#7c3aed",  # purple
        "核对": "#dc2626",  # red
        "写入": "#ec4899",  # pink
        "执行": "#3b82f6",  # blue
    }.get(role, "#a0a0b0")


class AgentTreeLayout:
    """Populate spawn_x / join_x / depth_y on session.agent_tree."""

    def layout(self, session: SessionVizData) -> None:
        """Mutates ``session.agent_tree`` and ``session.agent_layout_summary``."""
        if not session.timeline:
            return

        # Anchor relative-time x to the session's start_time when present.
        # Important: ``or`` falls through on 0 (falsy), which would silently
        # shift every spawn_x. Use an explicit None check.
        base_time = session.start_time
        if base_time is None:
            base_time = session.timeline[0].start_time

        def _rel(t: float) -> float:
            return max(0.0, t - base_time)

        # ---- 1. Auto-promote: synthesize sub-agent nodes from Agent bars
        #         if agent_tree is empty or only has the implicit primary node.
        nodes = list(session.agent_tree)
        has_real_root = any(n.parent_id is not None for n in nodes)
        spawn_events = self._find_spawn_events(session.timeline)

        if not has_real_root and spawn_events:
            # Drop the implicit single primary node, then synthesize.
            nodes = [n for n in nodes if n.parent_id is not None] or [
                AgentTreeNode(
                    agent_id="primary",
                    name="primary-agent",
                    parent_id=None,
                    session_ref=session.session_id,
                    status=BarStatus.SUCCESS,
                )
            ]
            synthesized = self._synthesize_nodes(spawn_events, session.session_id)
            # Avoid duplicates if user already added some
            existing = {n.agent_id for n in nodes}
            for s in synthesized:
                if s.agent_id not in existing:
                    nodes.append(s)
            session.agent_tree = nodes

        # ---- 2. Index existing nodes for lookup
        node_by_id: dict[str, AgentTreeNode] = {n.agent_id: n for n in nodes}
        consumed_spawns: set[int] = set()

        # ---- 3. Walk spawn events and assign spawn_x / depth_y
        for idx, ev in enumerate(spawn_events):
            node = self._match_node(ev, nodes, consumed_spawns)
            if node is None:
                continue
            consumed_spawns.add(idx)
            node.spawn_x = _rel(ev["start_time"])
            # depth_y is 1..N based on insertion order
            node.depth_y = 1 + sum(
                1 for n in nodes if n.depth_y > 0 and n.agent_id != node.agent_id
            )
            node.role = ev.get("role") or _role_label_for(
                ev.get("subagent_type"), ev.get("subagent_description")
            )
            node.role_color = _role_color_for(node.role)

        # ---- 4. Compute join_x = end of last sub-agent activity after spawn_x
        for node in nodes:
            if node.parent_id is None or node.spawn_x is None:
                continue
            last_end = self._last_subagent_end_time(session.timeline, node, base_time)
            node.join_x = last_end if last_end is not None else node.spawn_x + 1.0

        # ---- 5. Compute aggregate summary — only when there are sub-agents
        subagent_nodes = [n for n in nodes if n.parent_id is not None]
        if not subagent_nodes:
            # No subs → leave summary empty so consumers can treat it as
            # "no waterfall / no spawn callout".
            session.agent_layout_summary = {}
        else:
            spawn_times = [n.spawn_x for n in subagent_nodes if n.spawn_x is not None]
            join_times = [n.join_x for n in subagent_nodes if n.join_x is not None]
            by_role = Counter(n.role for n in subagent_nodes if n.role)
            session.agent_layout_summary = {
                "spawn_time": min(spawn_times) if spawn_times else None,
                "join_time": max(join_times) if join_times else None,
                "subagent_count": len(subagent_nodes),
                "by_role": dict(by_role),
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_spawn_events(timeline: list[TimelineBar]) -> list[dict[str, Any]]:
        """Return list of {start_time, end_time, subagent_type, subagent_description, agent_id, role}."""
        events: list[dict[str, Any]] = []
        for bar in timeline:
            detail = bar.detail or {}
            is_spawn = (
                detail.get("isAgentInvocation")
                or detail.get("is_agent_invocation")
                or detail.get("subagent_type")
                or detail.get("subagent_description")
                or (
                    bar.label in ("Agent", "Task") and bar.category == OperationCategory.ORCHESTRATE
                )
            )
            if not is_spawn:
                continue
            events.append(
                {
                    "start_time": bar.start_time,
                    "end_time": bar.end_time,
                    "subagent_type": detail.get("subagent_type"),
                    "subagent_description": detail.get("subagent_description")
                    or detail.get("description"),
                    "agent_id": detail.get("agent_id"),
                    "role": detail.get("role"),
                    "bar_id": bar.id,
                }
            )
        return events

    @staticmethod
    def _synthesize_nodes(
        spawn_events: list[dict[str, Any]],
        session_id: str,
    ) -> list[AgentTreeNode]:
        """Create AgentTreeNode from spawn events when none exist."""
        nodes: list[AgentTreeNode] = []
        seen: set[tuple[str | None, str | None]] = set()
        for ev in spawn_events:
            key = (ev.get("subagent_type"), ev.get("subagent_description"))
            if key in seen:
                continue
            seen.add(key)
            idx = len(nodes) + 1
            label = ev.get("subagent_description") or ev.get("subagent_type") or f"subagent-{idx}"
            nodes.append(
                AgentTreeNode(
                    agent_id=f"auto/{label}",
                    name=label,
                    parent_id="primary",
                    session_ref=session_id,
                    status=BarStatus.SUCCESS,
                )
            )
        return nodes

    @staticmethod
    def _match_node(
        ev: dict[str, Any],
        nodes: list[AgentTreeNode],
        consumed: set[int],
    ) -> AgentTreeNode | None:
        """Find a non-root node to attach this spawn event to."""
        candidates = [
            n for i, n in enumerate(nodes) if n.parent_id is not None and i not in consumed
        ]
        if not candidates:
            return None
        # 1) explicit agent_id
        if ev.get("agent_id"):
            for n in candidates:
                if n.agent_id == ev["agent_id"]:
                    return n
        # 2) match by name (description)
        desc = ev.get("subagent_description") or ev.get("subagent_type")
        if desc:
            for n in candidates:
                if n.name == desc:
                    return n
        # 3) fall back to first un-consumed candidate
        return candidates[0]

    @staticmethod
    def _last_subagent_end_time(
        timeline: list[TimelineBar],
        node: AgentTreeNode,
        base_time: float,
    ) -> float | None:
        """Approximate join time = last bar.end_time after node.spawn_x.

        Heuristic: pick the last bar whose detail carries the node's
        subagent_type, falling back to the latest bar after spawn.
        """
        if node.spawn_x is None:
            return None
        spawn_t = base_time + node.spawn_x
        sub_type = node.metadata.get("subagent_type") if node.metadata else None
        # Prefer bars tagged with the same subagent_type / name
        best = None
        for bar in timeline:
            if bar.start_time < spawn_t:
                continue
            detail = bar.detail or {}
            if sub_type and detail.get("subagent_type") == sub_type:
                best = bar.end_time
            elif node.name and node.name in (detail.get("subagent_description") or ""):
                best = bar.end_time
        # Fallback: last bar of any kind
        later = [b.end_time for b in timeline if b.start_time >= spawn_t]
        if best is not None:
            return max(0.0, max(best, max(later) if later else best) - base_time)
        if not later:
            return None
        return max(0.0, max(later) - base_time)


__all__ = ["AgentTreeLayout"]
