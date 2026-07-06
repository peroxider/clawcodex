"""Tests for F-149 Automatic Task Decomposition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (
    Ambiguity,
    AmbiguityDetector,
    AmbiguityReport,
    DecompositionPlan,
    ProposedTask,
    TaskDecomposer,
    TaskDecompositionError,
)
from clawcodex_ext.logical_kanban.audit import get_audit_log
from clawcodex_ext.logical_kanban.fuzzy_patterns import (
    BUILT_IN_PATTERN_LIBRARY,
    FuzzyPattern,
)
from clawcodex_ext.logical_kanban.fuzzy_types import Interpretation
from clawcodex_ext.providers.base import BaseProvider, ChatResponse
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.errors import ToolInputError
from clawcodex_ext.tool_system.tools.task_decompose import (
    TaskDecomposeTool,
    _task_decompose_call,
)


def _set_lkb(monkeypatch: Any, enabled: bool) -> None:
    from clawcodex_ext.feature_gate import get_registry

    monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)


def _set_todo_v2(monkeypatch: Any, enabled: bool) -> None:
    monkeypatch.setattr(
        "clawcodex_ext.tool_system.tools.task_decompose.is_todo_v2_enabled",
        lambda: enabled,
    )


class _StubProvider(BaseProvider):
    """Provider that returns a fixed decomposition JSON response."""

    def __init__(self, response_json: dict[str, Any] | None = None) -> None:
        super().__init__(api_key="test")
        self.response_json = response_json or _default_plan_json()
        self.calls: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        return ChatResponse(
            content=json.dumps(self.response_json),
            model="stub",
            usage={"input_tokens": 10, "output_tokens": 50},
            finish_reason="stop",
        )

    def chat_stream(
        self,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError

    def get_available_models(self) -> list[str]:
        return ["stub"]


def _default_plan_json() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "proposedTaskId": "tmp-a",
                "subject": "Set up project scaffold",
                "description": "Create the initial directory structure and config files.",
                "activeForm": "Setting up project scaffold",
                "acceptanceCriteria": ["Config file exists", "Directory structure matches spec"],
                "blockedBy": [],
                "lkbMetadata": {
                    "assertions": ["ConfigFileExists()"],
                    "acceptance_proof": "Config file created",
                    "assumptions": [],
                    "strict_acceptance": False,
                },
            },
            {
                "proposedTaskId": "tmp-b",
                "subject": "Implement core logic",
                "description": "Write the main algorithm implementation.",
                "activeForm": "Implementing core logic",
                "acceptanceCriteria": ["Unit tests pass", "Algorithm returns correct output"],
                "blockedBy": ["tmp-a"],
                "lkbMetadata": {
                    "assertions": ["AlgorithmCorrect()"],
                    "acceptance_proof": "Tests pass",
                    "assumptions": ["Input format is stable"],
                    "strict_acceptance": True,
                },
            },
        ],
        "dependencies": [["tmp-a", "tmp-b"]],
        "assumptions": ["Input format is stable"],
    }


def _cyclic_plan_json() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "proposedTaskId": "tmp-a",
                "subject": "Task A",
                "description": "Depends on B.",
                "activeForm": "Working on task A",
                "acceptanceCriteria": ["A is done"],
                "blockedBy": ["tmp-b"],
                "lkbMetadata": {},
            },
            {
                "proposedTaskId": "tmp-b",
                "subject": "Task B",
                "description": "Depends on A.",
                "activeForm": "Working on task B",
                "acceptanceCriteria": ["B is done"],
                "blockedBy": ["tmp-a"],
                "lkbMetadata": {},
            },
        ],
        "dependencies": [["tmp-b", "tmp-a"], ["tmp-a", "tmp-b"]],
        "assumptions": [],
    }


def _vague_plan_json() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "proposedTaskId": "tmp-a",
                "subject": "Make it faster",
                "description": "Improve performance somehow.",
                "activeForm": "Making it faster",
                "acceptanceCriteria": ["It should be much faster"],
                "blockedBy": [],
                "lkbMetadata": {},
            }
        ],
        "dependencies": [],
        "assumptions": [],
    }


def _vague_pattern_library() -> Any:
    """Pattern library that flags vague performance phrases as major ambiguity."""
    return BUILT_IN_PATTERN_LIBRARY.add(
        FuzzyPattern(
            pattern_id="P-VAGUE-PERF-001",
            category="semantic_vagueness",
            severity="major",
            matcher=lambda t: "faster" in t.lower() or "somehow" in t.lower(),
            interpretations=(
                Interpretation(
                    code="vague_speedup",
                    formalization="PerformanceImprovement({metric}, {target})",
                    base_confidence=0.60,
                ),
                Interpretation(
                    code="vague_feeling",
                    formalization="SubjectivePerformance({metric})",
                    base_confidence=0.40,
                ),
            ),
            clarification_prompt="请定义具体的性能指标与目标值。",
        )
    )


class TestTaskDecomposer:
    def test_simple_goal_produces_multiple_tasks(self, tmp_path: Any) -> None:
        provider = _StubProvider(_default_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("Build a feature", max_steps=8)

        assert isinstance(plan, DecompositionPlan)
        assert len(plan.tasks) == 2
        assert plan.tasks[0].subject == "Set up project scaffold"
        assert plan.tasks[1].subject == "Implement core logic"
        assert plan.validation_run is not None
        assert plan.validation_run.result == "pass"

    def test_dependency_ordering_is_preserved(self, tmp_path: Any) -> None:
        provider = _StubProvider(_default_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("Build a feature", max_steps=8)

        assert plan.dependencies == (("tmp-a", "tmp-b"),)
        assert plan.tasks[1].blocked_by == ("tmp-a",)

    def test_rejects_cyclic_generated_plan(self, tmp_path: Any) -> None:
        provider = _StubProvider(_cyclic_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("Cyclic work", max_steps=8)

        assert plan.validation_run is not None
        assert plan.validation_run.result == "fail"
        issue_codes = {issue.code for issue in plan.validation_run.issues}
        assert "decomposition_cyclic_dependency" in issue_codes

    def test_detects_vague_acceptance_criteria(self, tmp_path: Any) -> None:
        provider = _StubProvider(_vague_plan_json())
        detector = AmbiguityDetector(library=_vague_pattern_library())
        decomposer = TaskDecomposer(llm_provider=provider, ambiguity_detector=detector)

        plan = decomposer.decompose("Make it faster", max_steps=8)

        assert plan.ambiguity_report is not None
        assert plan.ambiguity_report.needs_clarification is True
        assert plan.validation_run is not None
        assert plan.validation_run.result == "fail"
        issue_codes = {issue.code for issue in plan.validation_run.issues}
        assert "decomposition_ambiguous_criterion" in issue_codes

    def test_missing_provider_raises(self, tmp_path: Any) -> None:
        decomposer = TaskDecomposer(llm_provider=None)
        with pytest.raises(ValueError, match="requires an LLM provider"):
            decomposer.decompose("Build a feature")

    def test_invalid_json_retries_then_raises(self, tmp_path: Any) -> None:
        class BadProvider(BaseProvider):
            def __init__(self) -> None:
                super().__init__(api_key="test")

            def chat(
                self,
                messages: list[Any],
                tools: list[dict[str, Any]] | None = None,
                **kwargs: Any,
            ) -> ChatResponse:
                return ChatResponse(
                    content="not json",
                    model="bad",
                    usage={},
                    finish_reason="stop",
                )

            def chat_stream(self, messages, tools=None, **kwargs):
                raise NotImplementedError

            def get_available_models(self):
                return ["bad"]

        decomposer = TaskDecomposer(llm_provider=BadProvider(), max_retries=1)
        with pytest.raises(TaskDecompositionError):
            decomposer.decompose("Build a feature")

    def test_emits_audit_event(self, tmp_path: Any) -> None:
        provider = _StubProvider(_default_plan_json())
        decomposer = TaskDecomposer(llm_provider=provider)

        plan = decomposer.decompose("Build a feature", max_steps=8)

        # The decomposer creates a validation run and emits an audit event.
        assert plan.validation_run is not None
        assert plan.validation_run.validation_run_id.startswith("V-")


class TestTaskDecomposeTool:
    def _make_context(self, tmp_path: Any) -> ToolContext:
        return ToolContext(workspace_root=tmp_path, session_id="S-f149")

    def test_tool_available_only_when_both_gates_enabled(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        assert TaskDecomposeTool.is_enabled() is True

        _set_todo_v2(monkeypatch, False)
        assert TaskDecomposeTool.is_enabled() is False

        _set_todo_v2(monkeypatch, True)
        _set_lkb(monkeypatch, False)
        assert TaskDecomposeTool.is_enabled() is False

    def test_tool_returns_plan_without_mutating_context(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        ctx = self._make_context(tmp_path)
        ctx._active_provider = _StubProvider(_default_plan_json())

        result = _task_decompose_call({"goal": "Build a feature"}, ctx)

        output = result.output
        assert output["decompositionRunId"]
        assert len(output["tasks"]) == 2
        assert output["validation"]["result"] == "pass"
        assert ctx.tasks == {}
        assert ctx.todos == []

    def test_tool_emits_audit_event_to_context_log(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        ctx = self._make_context(tmp_path)
        ctx._active_provider = _StubProvider(_default_plan_json())

        _task_decompose_call({"goal": "Build a feature"}, ctx)

        events = get_audit_log(ctx).query(event_type="lkb_decomposition_proposed")
        assert len(events) == 1
        assert events[0].payload["taskCount"] == 2

    def test_tool_reports_validation_failure_for_cyclic_plan(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        ctx = self._make_context(tmp_path)
        ctx._active_provider = _StubProvider(_cyclic_plan_json())

        result = _task_decompose_call({"goal": "Cyclic work"}, ctx)

        assert result.output["validation"]["result"] == "fail"
        assert any(
            issue["code"] == "decomposition_cyclic_dependency"
            for issue in result.output["validation"]["issues"]
        )

    def test_tool_reports_no_provider_error(
        self,
        tmp_path: Any,
        monkeypatch: Any,
    ) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        ctx = self._make_context(tmp_path)
        ctx._active_provider = None

        result = _task_decompose_call({"goal": "Build a feature"}, ctx)

        assert result.is_error is True
        assert "No active LLM provider" in result.output["error"]

    def test_tool_validates_max_steps_bounds(self, tmp_path: Any, monkeypatch: Any) -> None:
        _set_lkb(monkeypatch, True)
        _set_todo_v2(monkeypatch, True)
        ctx = self._make_context(tmp_path)
        ctx._active_provider = _StubProvider(_default_plan_json())

        with pytest.raises(ToolInputError, match="max_steps"):
            _task_decompose_call({"goal": "x", "max_steps": 0}, ctx)

        with pytest.raises(ToolInputError, match="max_steps"):
            _task_decompose_call({"goal": "x", "max_steps": 21}, ctx)
