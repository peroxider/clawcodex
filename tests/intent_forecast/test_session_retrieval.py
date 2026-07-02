from __future__ import annotations

from clawcodex_ext.intent_forecast.session_retrieval import rank_session_rows


def test_session_retrieval_prefers_changed_file_overlap_over_recency() -> None:
    rows = [
        {
            "session_id": "orchestrator",
            "title": "Orchestrator cleanup",
            "last_updated": 200,
            "summary": {"files_touched": ["extensions/orchestrator/orchestrator.py"]},
        },
        {
            "session_id": "forecast",
            "title": "Intent Forecast fallback",
            "last_updated": 100,
            "summary": {
                "files_touched": ["clawcodex_ext/intent_forecast/service.py"],
                "next_action_candidates": ["Run focused tests"],
            },
        },
    ]

    ranked = rank_session_rows(
        rows,
        cwd="C:/WorkSpace/clawcodex",
        changed_files=["clawcodex_ext/intent_forecast/service.py"],
        recent_text="continue intent forecast",
        limit=2,
    )

    assert [row["session_id"] for row in ranked] == ["forecast", "orchestrator"]
    assert ranked[0]["relevance_score"] > ranked[1]["relevance_score"]
