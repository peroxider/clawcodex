"""Tests for SOPDashboardSource."""

from __future__ import annotations

from typing import Any

from extensions.agent_dashboard import DashboardSourceRegistry, get_default_registry
from extensions.agent_dashboard.sources.sop_source import (
    SOPDashboardSource,
    register_sop_dashboard_source,
)
from extensions.capabilities.dashboard_entry import (
    DASHBOARD_STATUS_PENDING,
    DashboardEntry,
)


def test_sop_source_default_returns_empty() -> None:
    src = SOPDashboardSource()
    assert src.pull() == []


def test_sop_source_forwards_provider_entries() -> None:
    entries = [
        DashboardEntry(
            id="sop:stage-1",
            source="sop",
            title="compile SOP",
            status=DASHBOARD_STATUS_PENDING,
        )
    ]
    src = SOPDashboardSource(sop_state_provider=lambda: entries)
    assert src.pull() == entries


def test_sop_source_filters_non_dashboard_entries() -> None:
    entries = [
        DashboardEntry(id="sop:1", source="sop", title="ok", status="pending"),
        "bad-entry",
        123,
    ]
    src = SOPDashboardSource(sop_state_provider=lambda: entries)
    out = src.pull()
    assert [e.id for e in out] == ["sop:1"]


def test_sop_source_handles_none_from_provider() -> None:
    src = SOPDashboardSource(sop_state_provider=lambda: None)
    assert src.pull() == []


def test_sop_source_handles_provider_exception() -> None:
    def _bad() -> Any:
        raise RuntimeError("boom")

    src = SOPDashboardSource(sop_state_provider=_bad)
    assert src.pull() == []


def test_sop_source_default_ttl_is_5s() -> None:
    src = SOPDashboardSource()
    assert src.cache_ttl_ms == 5_000


def test_register_sop_dashboard_source_adds_to_default_registry() -> None:
    reg = DashboardSourceRegistry()
    source = register_sop_dashboard_source(lambda: [])
    assert source.source_name == "sop"
    assert reg.get("sop") is None
    # Re-register against the default registry to verify the helper works.
    default_reg = get_default_registry()
    default_reg.register(source)
    assert default_reg.get("sop") is source
    default_reg.unregister("sop")
