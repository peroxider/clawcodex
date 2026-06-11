"""Tests for AgentTreeLayout (F-95 spawn_x / join_x inference)."""

from __future__ import annotations

from extensions.visualizer.builders.agent_tree_layout import AgentTreeLayout
from extensions.visualizer.models.viz_models import (
    AgentTreeNode,
    BarStatus,
    BarType,
    SessionVizData,
    TimelineBar,
)


def _bar(label: str, start: float, end: float, **detail_extra) -> TimelineBar:
    det = {"tool_name": label}
    det.update(detail_extra)
    return TimelineBar(
        id=f"b-{label}-{start}",
        type=BarType.TOOL_CALL,
        label=label,
        start_time=start,
        end_time=end,
        duration_ms=int((end - start) * 1000),
        detail=det,
    )


def _session(start: float, end: float, *bars: TimelineBar) -> SessionVizData:
    viz = SessionVizData(
        session_id="s",
        start_time=start,
        end_time=end,
    )
    viz.timeline = list(bars)
    viz.agent_tree = [AgentTreeNode(
        agent_id="primary",
        name="primary-agent",
        parent_id=None,
        session_ref="s",
    )]
    return viz


class TestAgentTreeLayoutEmpty:
    def test_empty_timeline_is_noop(self):
        viz = SessionVizData(session_id="s", start_time=0, end_time=10)
        AgentTreeLayout().layout(viz)
        assert viz.agent_layout_summary == {}

    def test_no_agent_calls_leaves_root_alone(self):
        viz = _session(0, 100,
            _bar("Read", 5, 10),
            _bar("Bash", 15, 25),
        )
        AgentTreeLayout().layout(viz)
        # Primary node untouched
        assert viz.agent_tree[0].spawn_x is None
        assert viz.agent_tree[0].join_x is None
        assert viz.agent_layout_summary == {}


class TestAgentTreeLayoutSingleSubagent:
    def test_synthesizes_subagent_from_agent_call(self):
        viz = _session(0, 100,
            _bar("Read", 5, 10),
            _bar("Agent", 30, 40, subagent_type="review",
                 subagent_description="防作弊", isAgentInvocation=True),
            _bar("Write", 50, 60),
        )
        AgentTreeLayout().layout(viz)
        assert len(viz.agent_tree) == 2
        sub = [n for n in viz.agent_tree if n.parent_id][0]
        assert sub.spawn_x == 30.0
        # join_x spans through follow-up activity so the waterfall branch
        # can show the sub-agent's progress window instead of an empty lane.
        assert sub.join_x == 60.0
        assert sub.depth_y == 1
        assert sub.role == "评审"
        assert sub.role_color == "#7c3aed"

    def test_layout_summary_counts(self):
        viz = _session(0, 200,
            _bar("Agent", 30, 40, subagent_type="review",
                 subagent_description="A", isAgentInvocation=True),
            _bar("Agent", 80, 90, subagent_type="verify",
                 subagent_description="B", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        summary = viz.agent_layout_summary
        assert summary["subagent_count"] == 2
        assert summary["spawn_time"] == 30.0
        assert summary["join_time"] == 90.0
        assert summary["by_role"] == {"评审": 1, "核对": 1}


class TestAgentTreeLayoutMultipleSubagents:
    def test_depth_y_stacked(self):
        viz = _session(0, 300,
            _bar("Agent", 30, 40, subagent_type="review", subagent_description="A", isAgentInvocation=True),
            _bar("Agent", 80, 90, subagent_type="verify", subagent_description="B", isAgentInvocation=True),
            _bar("Agent", 150, 160, subagent_type="verify", subagent_description="C", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        subs = [n for n in viz.agent_tree if n.parent_id]
        depth_ys = sorted([n.depth_y for n in subs])
        assert depth_ys == [1, 2, 3]


class TestAgentTreeLayoutRobustness:
    def test_layout_never_raises_on_empty_agents(self):
        """agent_tree empty + no timeline should not raise."""
        viz = SessionVizData(session_id="s", start_time=0, end_time=10)
        AgentTreeLayout().layout(viz)
        # No crash, no nodes added
        assert viz.agent_tree == []

    def test_preserves_existing_root_node(self):
        """An explicit root node should be kept even when we synthesize subs."""
        viz = _session(0, 100,
            _bar("Agent", 30, 40, subagent_type="review",
                 subagent_description="X", isAgentInvocation=True),
        )
        original_root = viz.agent_tree[0]
        AgentTreeLayout().layout(viz)
        # Root still there
        assert any(n.agent_id == original_root.agent_id for n in viz.agent_tree)

    def test_is_agent_invocation_snake_case_also_recognized(self):
        viz = _session(0, 100,
            _bar("Task", 30, 40, is_agent_invocation=True,
                 subagent_type="verify", subagent_description="Y"),
        )
        AgentTreeLayout().layout(viz)
        assert len([n for n in viz.agent_tree if n.parent_id]) == 1
