"""Tests for Layer-2 contracts: DashboardEntry + DashboardSource."""

from __future__ import annotations

from typing import Any

import pytest

from extensions.capabilities.dashboard_entry import (
    DASHBOARD_STATUS_BLOCKED,
    DASHBOARD_STATUS_COMPLETED,
    DASHBOARD_STATUS_IN_PROGRESS,
    DASHBOARD_STATUS_PENDING,
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSource,
    filter_entries,
    normalize_source_name,
)


# ---------------------------------------------------------------------------
# DashboardEntry
# ---------------------------------------------------------------------------


def test_dashboard_entry_minimal_construction() -> None:
    entry = DashboardEntry(id="goal:t1", source="goal", title="Build X")
    assert entry.id == "goal:t1"
    assert entry.source == "goal"
    assert entry.title == "Build X"
    assert entry.status == "pending"
    assert entry.detail == ""
    assert entry.progress_pct is None
    assert entry.tags == []
    assert entry.updated_at_ms == 0
    assert entry.source_session_id is None
    assert entry.parent_id is None
    assert entry.owner is None


def test_dashboard_entry_is_immutable() -> None:
    entry = DashboardEntry(id="t:1", source="task", title="x")
    with pytest.raises(Exception):
        entry.title = "y"  # type: ignore[misc]


def test_dashboard_entry_progress_clamps_to_zero_one() -> None:
    over = DashboardEntry(id="t:1", source="t", title="x", progress_pct=1.5)
    under = DashboardEntry(id="t:2", source="t", title="x", progress_pct=-0.3)
    none = DashboardEntry(id="t:3", source="t", title="x", progress_pct=None)
    assert over.progress_pct == 1.0
    assert under.progress_pct == 0.0
    assert none.progress_pct is None


def test_dashboard_entry_invalid_progress_becomes_zero() -> None:
    # ``float("nan")`` is the common case to defend against — a
    # buggy source shouldn't crash the dashboard.
    entry = DashboardEntry(id="t:1", source="t", title="x", progress_pct=float("nan"))
    # NaN clamps to 0.0 in our normalization (it's < 0.0 returns False
    # but max(0,0) still gives 0; min(0,1) is 0).
    assert entry.progress_pct == 0.0


def test_dashboard_entry_tags_none_becomes_empty() -> None:
    entry = DashboardEntry(id="t:1", source="t", title="x", tags=None)  # type: ignore[arg-type]
    assert entry.tags == []


def test_dashboard_entry_to_dict_round_trip() -> None:
    entry = DashboardEntry(
        id="g:t1",
        source="goal",
        title="X",
        status="in_progress",
        detail="d",
        source_session_id="t1",
        progress_pct=0.5,
        parent_id="p",
        order=2,
        tags=["a", "b"],
        owner="o",
        updated_at_ms=1234,
    )
    d = entry.to_dict()
    assert d["id"] == "g:t1"
    assert d["source"] == "goal"
    assert d["title"] == "X"
    assert d["status"] == "in_progress"
    assert d["detail"] == "d"
    assert d["source_session_id"] == "t1"
    assert d["progress_pct"] == 0.5
    assert d["parent_id"] == "p"
    assert d["order"] == 2
    assert d["tags"] == ["a", "b"]
    assert d["owner"] == "o"
    assert d["updated_at_ms"] == 1234


def test_dashboard_statuses_constant_includes_known_values() -> None:
    assert DASHBOARD_STATUS_PENDING in DASHBOARD_STATUSES
    assert DASHBOARD_STATUS_IN_PROGRESS in DASHBOARD_STATUSES
    assert DASHBOARD_STATUS_COMPLETED in DASHBOARD_STATUSES
    assert DASHBOARD_STATUS_BLOCKED in DASHBOARD_STATUSES


# ---------------------------------------------------------------------------
# DashboardSource (Protocol runtime check)
# ---------------------------------------------------------------------------


def test_dashboard_source_protocol_accepts_structural_match() -> None:
    class _Source:
        source_name = "synthetic"
        cache_ttl_ms = 1000

        def pull(self, **filters: Any) -> list[DashboardEntry]:
            return [DashboardEntry(id="s:1", source="synthetic", title="x")]

    src = _Source()
    assert isinstance(src, DashboardSource)
    assert src.source_name == "synthetic"
    assert src.pull() == [
        DashboardEntry(id="s:1", source="synthetic", title="x")
    ]


# ---------------------------------------------------------------------------
# normalize_source_name
# ---------------------------------------------------------------------------


def test_normalize_source_name_lowercases_and_strips() -> None:
    assert normalize_source_name(" Goal ") == "goal"
    assert normalize_source_name("orchestrator-state") == "orchestrator_state"
    assert normalize_source_name("TASK__v2") == "task_v2"
    assert normalize_source_name("") == ""


# ---------------------------------------------------------------------------
# filter_entries
# ---------------------------------------------------------------------------


def _sample_entries() -> list[DashboardEntry]:
    return [
        DashboardEntry(id="goal:t1", source="goal", title="g1", status="in_progress"),
        DashboardEntry(id="goal:t2", source="goal", title="g2", status="completed"),
        DashboardEntry(id="task:1", source="task", title="t1", status="pending"),
        DashboardEntry(id="task:2", source="task", title="t2", status="failed"),
    ]


def test_filter_entries_by_source() -> None:
    out = filter_entries(_sample_entries(), source="goal")
    assert [e.id for e in out] == ["goal:t1", "goal:t2"]


def test_filter_entries_by_status() -> None:
    out = filter_entries(_sample_entries(), status="failed")
    assert [e.id for e in out] == ["task:2"]


def test_filter_entries_by_id() -> None:
    out = filter_entries(_sample_entries(), entry_id="task:1")
    assert [e.id for e in out] == ["task:1"]


def test_filter_entries_combined() -> None:
    out = filter_entries(_sample_entries(), source="goal", status="completed")
    assert [e.id for e in out] == ["goal:t2"]


def test_filter_entries_no_filters_returns_all() -> None:
    out = filter_entries(_sample_entries())
    assert len(out) == 4
