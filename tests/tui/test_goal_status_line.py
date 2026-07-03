"""Spec-6 goal status indicator tests for the TUI status line."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from src.tui.state import AppState
from src.tui.widgets.status_line import _goal_status_segment


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("active", "Pursuing goal"),
        ("paused", "Goal paused (/goal resume)"),
        ("blocked", "Goal blocked (/goal resume)"),
        ("usage_limited", "Goal hit usage limits (/goal resume)"),
        ("budget_limited", "Goal unmet"),
        ("complete", "Goal achieved"),
    ],
)
def test_status_line_explains_all_goal_statuses(status: str, expected: str) -> None:
    state = AppState(model="test-model", provider="test-provider")
    state.set_goal_status(
        {
            "status": status,
            "tokenBudget": 100,
            "tokensUsed": 40,
            "timeUsedSeconds": 120,
        }
    )

    rendered = _goal_status_segment(state.goal_status)

    assert expected in rendered


def test_status_line_prefers_budget_usage_for_active_goal() -> None:
    state = AppState(model="test-model", provider="test-provider")
    state.set_goal_status(
        {
            "status": "active",
            "tokenBudget": 50_000,
            "tokensUsed": 12_500,
            "timeUsedSeconds": 120,
        }
    )

    rendered = _goal_status_segment(state.goal_status)

    assert "Pursuing goal (12.5K / 50K)" in rendered
