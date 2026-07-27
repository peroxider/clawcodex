"""Tests for the single current LKB feature flag."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAWCODEX_FEATURE_LKB_PLAN_GRAPH", raising=False)
    monkeypatch.delenv("LKB_FEATURE_LKB_PLAN_GRAPH", raising=False)


def test_plan_graph_can_be_disabled_by_host_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from clawcodex_ext.feature_gate import get_registry
    from lkb.flags import is_plan_graph_enabled

    monkeypatch.setitem(get_registry()._overrides, "LKB_PLAN_GRAPH", False)
    assert is_plan_graph_enabled() is False


def test_plan_graph_constant_name() -> None:
    from lkb.flags import PLAN_GRAPH_FEATURE_NAME

    assert PLAN_GRAPH_FEATURE_NAME == "LKB_PLAN_GRAPH"


def test_plan_graph_enabled_via_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from lkb.flags import is_plan_graph_enabled

    monkeypatch.setenv("CLAWCODEX_FEATURE_LKB_PLAN_GRAPH", "1")
    assert is_plan_graph_enabled() is True


def test_programmatic_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from clawcodex_ext.feature_gate import get_registry
    from lkb.flags import is_plan_graph_enabled

    registry = get_registry()
    monkeypatch.setitem(registry._overrides, "LKB_PLAN_GRAPH", True)
    assert is_plan_graph_enabled() is True
