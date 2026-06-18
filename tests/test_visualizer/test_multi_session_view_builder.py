"""Tests for MultiSessionViewBuilder (F-95 waterfall payload assembly)."""

from __future__ import annotations

from extensions.visualizer.builders.multi_session_view_builder import (
    MultiSessionViewBuilder,
    _format_tick,
)
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
    viz.agent_tree = [
        AgentTreeNode(agent_id="primary", name="primary-agent", session_ref=session_id)
    ]
    return viz


class TestMultiSessionViewBuilderEmpty:
    def test_empty_input(self):
        out = MultiSessionViewBuilder().build([])
        assert out["sessions"] == []
        assert out["agents"] == []
        assert out["edges"] == []
        assert len(out["legend"]) == 8  # full OperationCategory set (F-95 follow-up)


class TestSingleSessionLegend:
    def test_legend_counts_match_categories(self):
        viz = _session(
            "s1",
            0,
            100,
            _bar("Read", 0, 5),
            _bar("Bash", 10, 20),
            _bar("Write", 30, 40),
            _bar(
                "Agent",
                50,
                60,
                subagent_type="review",
                subagent_description="X",
                isAgentInvocation=True,
            ),
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
        assert labels == [
            "读取",
            "执行",
            "写入",
            "编排",
            "推理",
            "轮次",
            "后台",
            "其他",
        ]

    def test_pre_set_other_llm_bar_is_refined(self):
        llm = TimelineBar(
            id="llm-1",
            type=BarType.LLM_CALL,
            label="LLM text",
            start_time=0,
            end_time=5,
            duration_ms=5000,
            detail={"text_preview": "thinking"},
        )
        llm.category = OperationCategory.LLM_TEXT
        viz = _session("s1", 0, 100, llm)
        out = MultiSessionViewBuilder().build([viz])
        legend = {l["category"]: l["count"] for l in out["legend"]}
        # F-95 follow-up: LLM_TEXT gets its own legend bucket (no longer
        # rolled into OTHER). The categorizer still refines the bar from
        # whatever was pre-set on the model into the LLM_TEXT category,
        # and the rendered tick carries the refined category.
        assert legend["llm_text"] == 1
        assert legend["other"] == 0
        assert out["sessions"][0]["ticks"][0]["category"] == "llm_text"


class TestSingleSessionLayout:
    def test_session_row_metadata_includes_tool_count(self):
        viz = _session(
            "s1",
            0,
            100,
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
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="防作弊",
                isAgentInvocation=True,
            ),
            _bar(
                "Agent",
                200,
                210,
                subagent_type="verify",
                subagent_description="解析崩溃",
                isAgentInvocation=True,
            ),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        callout = out["sessions"][0].get("spawnCallout")
        assert callout is not None
        assert callout["subagentCount"] == 2
        assert "派生 2 子agent" in callout["label"]


class TestAgentRows:
    def test_subagent_rows_present(self):
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="防作弊",
                isAgentInvocation=True,
            ),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        assert len(out["agents"]) == 1
        a = out["agents"][0]
        assert a["title"] == "防作弊"
        assert a["role"] == "评审"
        assert a["spawnX"] == 100.0

    def test_subagent_depth_y_stacked_below_session(self):
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="A",
                isAgentInvocation=True,
            ),
            _bar(
                "Agent",
                200,
                210,
                subagent_type="verify",
                subagent_description="B",
                isAgentInvocation=True,
            ),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        ys = sorted(a["depthY"] for a in out["agents"])
        assert ys == [1, 2]

    def test_subagent_rows_include_window_activity_ticks(self):
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="A",
                isAgentInvocation=True,
            ),
            _bar("Read", 120, 122),
            _bar("Bash", 130, 135),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        agent = out["agents"][0]
        labels = {t["label"] for t in agent["ticks"]}
        assert {"Read", "Bash"}.issubset(labels)
        assert agent["duration"] > 0

    def test_explicit_agent_id_activity_wins_over_window_fallback(self):
        explicit = _bar("Read", 20, 22)
        explicit.agent_id = "auto/A"
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="A",
                isAgentInvocation=True,
            ),
            explicit,
            _bar("Bash", 120, 125),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        labels = [t["label"] for t in out["agents"][0]["ticks"]]
        assert labels == ["Read"]


class TestEdges:
    def test_fork_and_join_edges_emitted(self):
        viz = _session(
            "s1",
            0,
            600,
            _bar(
                "Agent",
                100,
                110,
                subagent_type="review",
                subagent_description="X",
                isAgentInvocation=True,
            ),
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
    def test_tick_labels_cover_activity_range(self):
        viz = _session(
            "s1",
            0,
            1800,
            _bar("Read", 0, 5),
            _bar("Bash", 60, 120),
        )
        AgentTreeLayout().layout(viz)
        out = MultiSessionViewBuilder().build([viz])
        tr = out["timeRange"]
        assert tr["min"] == 0.0
        assert tr["max"] == 120.0
        assert len(tr["tickLabels"]) >= 2
        # First label should be the zero tick in mm:ss.SSS form.
        assert tr["tickLabels"][0] == "00:00.000"

    def test_format_tick_zero(self):
        assert _format_tick(0) == "00:00.000"

    def test_format_tick_sub_second(self):
        # Sub-second values round to 3 decimal ms digits.
        assert _format_tick(0.5) == "00:00.500"
        assert _format_tick(0.001) == "00:00.001"
        assert _format_tick(0.9995) == "00:01.000"  # rounds up

    def test_format_tick_seconds_only(self):
        assert _format_tick(8) == "00:08.000"
        assert _format_tick(30) == "00:30.000"
        assert _format_tick(59) == "00:59.000"

    def test_format_tick_minutes(self):
        assert _format_tick(60) == "01:00.000"
        assert _format_tick(125) == "02:05.000"
        assert _format_tick(300) == "05:00.000"

    def test_format_tick_rolls_past_60_minutes(self):
        # 90 minutes -> minute column rolls past 60 (no hour rollover).
        assert _format_tick(90 * 60) == "90:00.000"
        assert _format_tick(125 * 60 + 7.25) == "125:07.250"

    def test_format_tick_millisecond_precision(self):
        # 8s + 500ms + 250us rounds to .500 (5-digit us input).
        assert _format_tick(8.5) == "00:08.500"
        assert _format_tick(0.123) == "00:00.123"

    def test_format_tick_negative_clamps_to_zero(self):
        # Defensive: negative seconds (shouldn't happen, but the
        # formatter used to crash on None) must not blow up.
        assert _format_tick(-5) == "00:00.000"
        assert _format_tick(None) == "00:00.000"

    def test_format_tick_no_chinese_format_remaining(self):
        # F-95 follow-up: the waterfall xAxis used to emit
        # ``5分钟`` / ``1小时30分钟``. None of those should survive
        # the conversion to mm:ss.SSS.
        for s in (0, 8, 60, 300, 3600, 5400, 7321.5):
            label = _format_tick(s)
            assert "分钟" not in label
            assert "小时" not in label
            assert "s" not in label  # no short suffix either
            # Always exactly mm:ss.SSS shape (with rolling minutes).
            assert label.count(":") == 1
            head, tail = label.split(":")
            assert len(head) >= 2 and head.isdigit()
            assert "." in tail
            sec_part, ms_part = tail.split(".")
            assert len(sec_part) == 2 and sec_part.isdigit()
            assert len(ms_part) == 3 and ms_part.isdigit()

    def test_time_range_ignores_late_session_end(self):
        viz = _session(
            "s1",
            0,
            3600,
            _bar("Read", 10, 10.05),
            _bar("Bash", 20, 20.1),
        )
        out = MultiSessionViewBuilder().build([viz])
        assert out["timeRange"]["min"] == 0.0
        assert out["timeRange"]["max"] == 20.1
