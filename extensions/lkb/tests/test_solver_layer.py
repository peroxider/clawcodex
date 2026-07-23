"""Tests for the F-138 solver adapter and pipeline layer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

try:
    from clawcodex_ext.feature_gate import get_registry
except ImportError:
    get_registry = None
from lkb import (
    ClingoSolverAdapter,
    DatalogSolverAdapter,
    Layer1SolverAdapter,
    LogicalKanbanService,
    ProposedChange,
    SolverPipeline,
    SolverRequest,
    Z3SolverAdapter,
    all_adapters,
    default_adapters,
)
from lkb.context_adapter import build_facts_snapshot
from lkb.solver_adapter import SolverAdapter, SolverResponse
from lkb.solver_pipeline import _merge_responses
from lkb.types import FactsSnapshot, ValidationIssue
try:
    from clawcodex_ext.tool_system.context import ToolContext
except ImportError:
    ToolContext = None  # standalone lkb
try:
    from src.tool_system.tools import TaskCreateTool, TaskUpdateTool
except ImportError:
    TaskCreateTool = TaskUpdateTool = None  # standalone lkb


def _set_lkb(monkeypatch, enabled: bool) -> None:
    try:
        from clawcodex_ext.feature_gate import get_registry

        monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)
    except (ImportError, AttributeError):
        pass  # standalone lkb: feature_gate not available


@pytest.fixture
def service() -> LogicalKanbanService:
    return LogicalKanbanService()


@pytest.fixture
def empty_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


def _add_task(
    context: ToolContext,
    task_id: str,
    *,
    status: str = "pending",
    blocked_by: list[str] | None = None,
    blocks: list[str] | None = None,
) -> None:
    context.tasks[task_id] = {
        "id": task_id,
        "subject": task_id,
        "description": task_id,
        "status": status,
        "blockedBy": list(blocked_by or []),
        "blocks": list(blocks or []),
        "metadata": {},
    }


def _snapshot(context: ToolContext) -> FactsSnapshot:
    return build_facts_snapshot(context)


class TestSolverAdapters:
    def test_layer1_adapter_passes_ready_task(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        adapter = Layer1SolverAdapter()
        request = SolverRequest(
            snapshot=_snapshot(empty_context),
            target_task_id="A",
            target_status="in_progress",
        )
        response = adapter.solve(request)
        assert response.result == "pass"
        assert "Ready(A)" in response.derived_facts

    def test_layer1_adapter_fails_blocked_task(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        adapter = Layer1SolverAdapter()
        request = SolverRequest(
            snapshot=_snapshot(empty_context),
            target_task_id="B",
            target_status="in_progress",
        )
        response = adapter.solve(request)
        assert response.result == "fail"
        assert response.violated_rule == "R-002"
        assert "A" in response.message

    def test_layer1_adapter_is_always_available(self) -> None:
        assert Layer1SolverAdapter().available() is True

    def test_datalog_adapter_reports_unavailable_without_souffle(self) -> None:
        adapter = DatalogSolverAdapter()
        with patch("shutil.which", return_value=None):
            assert adapter.available() is False
            response = adapter.solve(SolverRequest(snapshot=_empty_snapshot()))
            assert response.result == "unknown"
            assert response.error_info is not None
            assert response.error_info["reason"] == "engine_unavailable"

    def test_clingo_adapter_reports_unavailable_when_not_installed(self) -> None:
        adapter = ClingoSolverAdapter()
        with patch.object(
            adapter,
            "available",
            return_value=False,
        ):
            response = adapter.solve(SolverRequest(snapshot=_empty_snapshot()))
            assert response.result == "unknown"

    def test_z3_adapter_reports_unavailable_when_not_installed(self) -> None:
        adapter = Z3SolverAdapter()
        with patch.object(
            adapter,
            "available",
            return_value=False,
        ):
            response = adapter.solve(SolverRequest(snapshot=_empty_snapshot()))
            assert response.result == "unknown"

    def test_default_adapters_includes_only_layer1(self) -> None:
        adapters = default_adapters()
        assert len(adapters) == 1
        assert adapters[0].name == "layer1-python"

    def test_all_adapters_includes_every_layer(self) -> None:
        adapters = all_adapters()
        names = {a.name for a in adapters}
        assert names == {"layer1-python", "datalog-souffle", "asp-clingo", "smt-z3", "atp-tptp"}


class TestSolverPipeline:
    def test_empty_pipeline_returns_error(self) -> None:
        pipeline = SolverPipeline([])
        result = pipeline.validate(
            SolverRequest(snapshot=_empty_snapshot()),
            proposal_id="P-test",
        )
        assert result.result == "error"
        assert result.issues
        assert result.issues[0].code == "solver_pipeline_empty"

    def test_pipeline_passes_when_layer1_passes(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        pipeline = SolverPipeline(default_adapters())
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="A",
                target_status="in_progress",
            ),
            proposal_id="P-test",
            input_facts_hash="sha256:facts",
            ruleset_hash="sha256:rules",
        )
        assert result.result == "pass"
        assert result.engine == "layer1-python"
        assert result.input_facts_hash == "sha256:facts"
        assert result.ruleset_hash == "sha256:rules"
        assert len(result.solver_results) == 1
        assert result.solver_results[0]["adapter"] == "layer1-python"

    def test_pipeline_fails_when_layer1_fails(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        pipeline = SolverPipeline(default_adapters())
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="B",
                target_status="in_progress",
            ),
            proposal_id="P-test",
        )
        assert result.result == "fail"
        assert result.solver_results[0]["result"] == "fail"

    def test_pipeline_aggregates_unknown_as_unknown(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        pipeline = SolverPipeline(
            [
                Layer1SolverAdapter(),
                _AlwaysUnknownAdapter(),
            ]
        )
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="A",
                target_status="in_progress",
            ),
            proposal_id="P-test",
        )
        assert result.result == "unknown"
        assert any(r["adapter"] == "always-unknown" for r in result.solver_results)

    def test_pipeline_aggregates_fail_over_unknown(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        pipeline = SolverPipeline(
            [
                Layer1SolverAdapter(),
                _AlwaysUnknownAdapter(),
            ]
        )
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="B",
                target_status="in_progress",
            ),
            proposal_id="P-test",
        )
        assert result.result == "fail"

    def test_pipeline_timeout_denies_commit(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        pipeline = SolverPipeline([_SlowAdapter()])
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="A",
                target_status="in_progress",
            ),
            proposal_id="P-test",
            timeout_seconds=0.05,
        )
        assert result.result == "unknown"
        assert result.solver_results[0]["result"] == "timeout"

    def test_pipeline_surfaces_adapter_exception_as_error(self, empty_context: ToolContext) -> None:
        _add_task(empty_context, "A", status="pending")
        pipeline = SolverPipeline([_BrokenAdapter()])
        result = pipeline.validate(
            SolverRequest(
                snapshot=_snapshot(empty_context),
                target_task_id="A",
                target_status="in_progress",
            ),
            proposal_id="P-test",
        )
        assert result.result == "unknown"
        assert result.solver_results[0]["result"] == "error"
        assert "Boom" in result.solver_results[0]["message"]


class TestServiceSolverIntegration:
    def test_service_uses_pipeline_for_transition(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        _add_task(empty_context, "A", status="pending")
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "A", "status": "in_progress"},
        )
        _proposal, validation, _commit = service.run(change, empty_context)
        assert validation.result == "pass"
        assert validation.engine == "layer1-python"
        assert validation.solver_results
        assert validation.solver_results[0]["adapter"] == "layer1-python"

    def test_service_denies_blocked_transition_with_pipeline(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        _add_task(empty_context, "A", status="pending")
        _add_task(empty_context, "B", status="pending", blocked_by=["A"])
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "B", "status": "in_progress"},
        )
        _proposal, validation, commit = service.run(change, empty_context)
        assert validation.result == "fail"
        assert commit.committed is False
        assert validation.counterexample is not None
        assert validation.solver_results[0]["result"] == "fail"

    def test_service_denies_strict_acceptance_via_pipeline(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        _add_task(empty_context, "A", status="in_progress")
        empty_context.tasks["A"]["metadata"] = {"lkb": {"strict_acceptance": True}}
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "A", "status": "completed"},
        )
        _proposal, validation, commit = service.run(change, empty_context)
        assert validation.result == "fail"
        assert validation.issues[0].code == "completed_requires_acceptance_proof"
        assert commit.committed is False

    def test_service_unknown_solver_result_denies_commit(
        self, service: LogicalKanbanService, empty_context: ToolContext
    ) -> None:
        _add_task(empty_context, "A", status="pending")
        service.pipeline = SolverPipeline(
            [
                Layer1SolverAdapter(),
                _AlwaysUnknownAdapter(),
            ]
        )
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "A", "status": "in_progress"},
        )
        _proposal, validation, commit = service.run(change, empty_context)
        assert validation.result == "unknown"
        assert commit.committed is False
        assert validation.issues[0].code == "solver_unknown"

    def test_task_update_tool_schema_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path)
        task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
            "id"
        ]

        result = TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

        assert result.is_error is False
        assert result.output["success"] is True
        lkb = result.output["lkb"]
        assert lkb["engine"] == "layer1-python"
        assert lkb["inputFactsHash"].startswith("sha256:")
        assert "solverResults" in lkb["validation"]


class TestMergeResponses:
    def test_merge_collects_facts_and_traces(self) -> None:
        responses = [
            {
                "result": "pass",
                "derivedFacts": ["Ready(A)"],
                "proofTrace": [{"rule": "R-003", "premises": [], "conclusion": "Ready(A)"}],
                "message": "",
            },
            {
                "result": "fail",
                "derivedFacts": ["Blocked(B)"],
                "proofTrace": [{"rule": "R-002", "premises": [], "conclusion": "Blocked(B)"}],
                "violatedRule": "R-002",
                "message": "blocked",
                "cycleTasks": [],
            },
        ]
        facts, traces, violated_rule, message, cycle_tasks = _merge_responses(responses)
        assert set(facts) == {"Ready(A)", "Blocked(B)"}
        assert len(traces) == 2
        assert violated_rule == "R-002"
        assert message == "blocked"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _empty_snapshot() -> FactsSnapshot:
    return build_facts_snapshot(SimpleNamespace(tasks={}, todos=()))


class _AlwaysUnknownAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return "always-unknown"

    @property
    def version(self) -> str:
        return "0.0.0"

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        return SolverResponse(
            result="unknown",
            message="always unknown for testing",
        )


class _SlowAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return "slow"

    @property
    def version(self) -> str:
        return "0.0.0"

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        import time

        time.sleep(1.0)
        return SolverResponse(result="pass")


class _BrokenAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return "broken"

    @property
    def version(self) -> str:
        return "0.0.0"

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        raise RuntimeError("Boom")
