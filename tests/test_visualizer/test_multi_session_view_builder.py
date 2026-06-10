"""Tests for MultiSessionViewBuilder (F-95 waterfall payload assembly)."""

from __future__ import annotations

from extensions.visualizer.builders.multi_session_view_builder import MultiSessionViewBuilder
from extensions.visualizer.builders.agent_tree_layout import AgentTreeLayout
from extensions.visualizer.builders.operation_categorizer import OperationCategorizer
from extensions.visualizer.models.viz_models import (
    AgentTreeNode,
    BarType,
    OperationCategory,
    SessionVizData,
    TimelineBar,
)


def _bar(label: str, start: float, end: float, **det) -> TimelineBar:
    detail = {"tool_name": label, **(det or {})}
    b = TimelineBar(
        id=f"b-{label}-{int(start)}",
        type=BarType.TOOL_CALL,
        label=label,
        start_time=start,
        end_time=end,
        duration_ms=int((end - start) * 1000),
        detail=detail,
    )
    b.category = OperationCategorizer().categorize(b)
    return b


def _session(
    session_id: str,
    start: float,
    end: float,
    *bars: TimelineBar,
    model: str = "opus-4-7",
    status: str = "completed",
    detected_mode: str = "single",
) -> SessionVizData:
    viz = SessionVizData(
        session_id=session_id,
        start_time=start,
        end_time=end,
        model=model,
        status=status,
        detected_mode=detected_mode,
    )
    viz.timeline = list(bars)
    viz.agent_tree = [AgentTreeNode(agent_id="primary", name="primary-agent", session_ref=session_id)]
    return viz


class TestMultiSessionViewBuilderEmpty:
    def test_empty_input(self):
        out = MultiSessionViewBuilder().build([])
        assert out["sessions"] == []
        assert out["agents"] == []
        assert out["edges"] == []
        assert len(out["legend"]) == 5  # all 5 categories with count 0


class TestSingleSessionLegend:
    def test_legend_counts_match_categories(self):
        viz = _session("s1", 0, 100,
            _bar("Read", 0, 5),
            _bar("Bash", 10, 20),
            _bar("Write", 30, 40),
            _bar("Agent", 50, 60, subagent_type="review",
                 subagent_description="X", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        legend = {l["category"]: l["count"] for l in out["legend"]}
        assert legend["read"] == 1
        assert legend["execute"] == 1
        assert legend["write"] == 1
        assert legend["orchestrate"] == 1
        assert legend["other"] == 0

    def test_legend_has_zh_labels(self):
        viz = _session("s1", 0, 100, _bar("Read", 0, 5))
        out = MultiSessionViewBuilder().build([viz])
        labels = [l["label"] for l in out["legend"]]
        assert labels == ["读取", "执行", "写入", "编排", "其他"]


class TestSingleSessionLayout:
    def test_session_row_metadata_includes_tool_count(self):
        viz = _session("s1", 0, 100,
            _bar("Read", 0, 5),
            _bar("Bash", 10, 20),
            _bar("Write", 30, 40),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        assert "工具调用" in out["sessions"][0]["metadata"]

    def test_session_row_has_end_marker(self):
        viz = _session("s1", 0, 600, _bar("Read", 0, 5), status="success")
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        marker = out["sessions"][0].get("endMarker")
        assert marker is not None
        assert marker["x"] == 600.0
        assert "收工" in marker["label"]

    def test_spawn_callout_present_with_subs(self):
        viz = _session("s1", 0, 600,
            _bar("Agent", 100, 110, subagent_type="review",
                 subagent_description="防作弊", isAgentInvocation=True),
            _bar("Agent", 200, 210, subagent_type="verify",
                 subagent_description="解析崩溃", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        callout = out["sessions"][0].get("spawnCallout")
        assert callout is not None
        assert callout["subagentCount"] == 2
        assert "派生 2 子agent" in callout["label"]


class TestAgentRows:
    def test_subagent_rows_present(self):
        viz = _session("s1", 0, 600,
            _bar("Agent", 100, 110, subagent_type="review",
                 subagent_description="防作弊", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        assert len(out["agents"]) == 1
        a = out["agents"][0]
        assert a["title"] == "防作弊"
        assert a["role"] == "评审"
        assert a["spawnX"] == 100.0

    def test_subagent_depth_y_stacked_below_session(self):
        viz = _session("s1", 0, 600,
            _bar("Agent", 100, 110, subagent_type="review", subagent_description="A", isAgentInvocation=True),
            _bar("Agent", 200, 210, subagent_type="verify", subagent_description="B", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        ys = sorted(a["depthY"] for a in out["agents"])
        assert ys == [1, 2]


class TestEdges:
    def test_fork_and_join_edges_emitted(self):
        viz = _session("s1", 0, 600,
            _bar("Agent", 100, 110, subagent_type="review", subagent_description="X", isAgentInvocation=True),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        # 1 fork + 1 join
        types = [e["type"] for e in out["edges"]]
        assert "fork" in types
        assert "join" in types
        for e in out["edges"]:
            assert e["color"] == "#ea7ccc"


class TestTimeRange:
    def test_tick_labels_cover_full_range(self):
        viz = _session("s1", 0, 1800,
            _bar("Read", 0, 5),
            _bar("Bash", 60, 120),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        tr = out["timeRange"]
        assert tr["min"] == 0.0
        assert tr["max"] >= 1800.0
        assert len(tr["tickLabels"]) >= 2
        # First label should be 0
        assert tr["tickLabels"][0] == "0分钟"
