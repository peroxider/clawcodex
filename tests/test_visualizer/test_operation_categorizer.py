"""Tests for OperationCategorizer (F-95 legend mapper)."""

from __future__ import annotations

import pytest

from extensions.visualizer.builders.operation_categorizer import OperationCategorizer
from extensions.visualizer.models.viz_models import (
    BarStatus,
    BarType,
    OperationCategory,
    TimelineBar,
)


def _bar(label: str, detail: dict | None = None, bar_type: BarType = BarType.TOOL_CALL) -> TimelineBar:
    return TimelineBar(
        id=f"x-{label}",
        type=bar_type,
        label=label,
        start_time=0.0,
        end_time=1.0,
        duration_ms=1000,
        detail=detail or {"tool_name": label},
    )


class TestOperationCategorizerToolRules:
    def test_read_tools(self):
        cat = OperationCategorizer()
        for name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch", "LS"):
            assert cat.categorize(_bar(name)) == OperationCategory.READ, name

    def test_execute_tools(self):
        cat = OperationCategorizer()
        for name in ("Bash", "Execute", "TaskKill", "BashOutput", "KillShell", "Shell"):
            assert cat.categorize(_bar(name)) == OperationCategory.EXECUTE, name

    def test_write_tools(self):
        cat = OperationCategorizer()
        for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "TodoWrite", "Patch"):
            assert cat.categorize(_bar(name)) == OperationCategory.WRITE, name

    def test_orchestrate_tools(self):
        cat = OperationCategorizer()
        for name in ("Agent", "Task", "SendMessage", "TeamCreate"):
            assert cat.categorize(_bar(name)) == OperationCategory.ORCHESTRATE, name

    def test_unknown_tool_is_other(self):
        cat = OperationCategorizer()
        assert cat.categorize(_bar("MagicalUnicorn")) == OperationCategory.OTHER


class TestOperationCategorizerExplicitFlags:
    def test_isAgentInvocation_flag(self):
        cat = OperationCategorizer()
        bar = _bar("Bash", detail={
            "tool_name": "Bash",
            "isAgentInvocation": True,
        })
        # Explicit flag wins over tool_name match
        assert cat.categorize(bar) == OperationCategory.ORCHESTRATE

    def test_is_agent_invocation_snake_case(self):
        cat = OperationCategorizer()
        bar = _bar("Read", detail={
            "tool_name": "Read",
            "is_agent_invocation": True,
        })
        assert cat.categorize(bar) == OperationCategory.ORCHESTRATE

    def test_pre_set_category_returned(self):
        cat = OperationCategorizer()
        bar = _bar("Bash")
        bar.category = OperationCategory.WRITE
        assert cat.categorize(bar) == OperationCategory.WRITE


class TestOperationCategorizerBarTypeFallback:
    def test_phase_type_is_orchestrate(self):
        cat = OperationCategorizer()
        bar = _bar("phase-1", bar_type=BarType.PHASE)
        bar.detail = {}  # no tool_name
        assert cat.categorize(bar) == OperationCategory.ORCHESTRATE

    def test_session_type_is_orchestrate(self):
        cat = OperationCategorizer()
        bar = _bar("session-root", bar_type=BarType.SESSION)
        bar.detail = {}
        assert cat.categorize(bar) == OperationCategory.ORCHESTRATE

    def test_text_type_is_other(self):
        cat = OperationCategorizer()
        bar = _bar("LLM text", bar_type=BarType.LLM_CALL)
        bar.detail = {}
        assert cat.categorize(bar) == OperationCategory.OTHER


class TestOperationCategoryColor:
    def test_legend_colors_distinct(self):
        colors = {c.color for c in OperationCategory}
        assert len(colors) == len(OperationCategory), "Categories must have distinct colors"

    def test_legend_labels_present(self):
        labels = {c.label for c in OperationCategory}
        # All five Chinese labels
        assert {"读取", "执行", "写入", "编排", "其他"} <= labels
