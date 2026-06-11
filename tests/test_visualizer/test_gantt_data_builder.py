from extensions.visualizer.builders.gantt_data_builder import GanttDataBuilder
from extensions.visualizer.models.viz_models import BarType, SessionVizData, TimelineBar


def test_gantt_bounds_use_visible_bars_not_session_end():
    session = SessionVizData(
        session_id="test-session",
        start_time=100.0,
        end_time=300.0,
        timeline=[
            TimelineBar(
                id="msg-1",
                type=BarType.CUSTOM,
                label="user",
                start_time=100.0,
                end_time=100.05,
                duration_ms=50,
            ),
            TimelineBar(
                id="llm-1",
                type=BarType.LLM_CALL,
                label="LLM text",
                start_time=100.2,
                end_time=100.3,
                duration_ms=100,
            ),
        ],
    )

    out = GanttDataBuilder().build(session)

    assert out["timeRange"] == {"min": 0, "max": 300}
    assert out["series"][0][9] == "custom"
    assert out["series"][1][9] == "llm_call"
