"""Tests for the F-138 Layer-4 SMT/Z3 solver adapter.

These tests exercise the full SMT encoding path. They are skipped when the
``z3-solver`` package is not importable so CI runs without the optional
extra stay green; the ``pytest.importorskip`` decorator handles that.

The adapter is also verified against ``SolverPipeline`` so the F-138
aggregation policy (``any fail → fail``, ``any uncertain → unknown``) is
exercised end-to-end, not just the adapter in isolation.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

z3 = pytest.importorskip("z3")

from clawcodex_ext.logical_kanban import (  # noqa: E402 - after importorskip
    Layer1SolverAdapter,
    LogicalKanbanService,
    ProposedChange,
    SolverAdapter,
    SolverPipeline,
    SolverRequest,
    SolverResponse,
    Z3SolverAdapter,
    extended_adapters,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot  # noqa: E402
from clawcodex_ext.logical_kanban.solver_adapter import (  # noqa: E402
    _parse_fact,
    encode_solver_literal,
)
from clawcodex_ext.logical_kanban.types import FactsSnapshot  # noqa: E402


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ctx_with(tasks: dict[str, dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(tasks=tasks, todos=())


def _snapshot(context: SimpleNamespace) -> FactsSnapshot:
    return build_facts_snapshot(context)


def _req(snapshot, *, target=None, status=None, strict=False, proof=None):
    return SolverRequest(
        snapshot=snapshot,
        target_task_id=target,
        target_status=status,
        strict_acceptance=strict,
        acceptance_proof_present=proof,
    )


def _task(
    task_id: str,
    *,
    status: str = "pending",
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    subject: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": task_id,
        "subject": subject if subject is not None else task_id,
        "description": description if description is not None else "",
        "status": status,
        "blocks": list(blocks or []),
        "blockedBy": list(blocked_by or []),
        "metadata": dict(metadata or {}),
    }
    return body


# ---------------------------------------------------------------------------
# Smoke / availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_available_when_z3_importable(self) -> None:
        assert Z3SolverAdapter().available() is True

    def test_version_matches_z3(self) -> None:
        adapter = Z3SolverAdapter()
        assert adapter.version == z3.get_version_string()

    def test_unavailable_when_z3_missing(self) -> None:
        adapter = Z3SolverAdapter()
        # Cache reset just in case the test order is randomised.
        adapter._cached_z3 = None
        with patch.object(adapter, "_import_z3", return_value=None):
            assert adapter.available() is False
            response = adapter.solve(_req(_snapshot(_ctx_with({}))))
        assert response.result == "unknown"
        assert response.error_info == {"reason": "engine_unavailable"}


class TestExtendedAdapters:
    def test_extended_adapters_keeps_layer1_first(self) -> None:
        adapters = extended_adapters()
        assert adapters[0].name == "layer1-python"

    def test_extended_adapters_includes_z3_when_available(self) -> None:
        names = {a.name for a in extended_adapters()}
        assert "smt-z3" in names


# ---------------------------------------------------------------------------
# Truth-table / decision coverage
# ---------------------------------------------------------------------------


class TestDecisionMatrix:
    def test_ready_task_passes(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        assert response.result == "pass"
        assert response.proof_trace
        assert response.proof_trace[0]["rule"] == "Z3-SAT"

    def test_blocked_task_fails_with_r002(self) -> None:
        ctx = _ctx_with(
            {
                "A": _task("A"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        snap = _snapshot(ctx)
        response = Z3SolverAdapter().solve(_req(snap, target="B", status="in_progress"))
        assert response.result == "fail"
        assert response.violated_rule == "R-002"
        assert "A" in response.message

    def test_cycle_task_prefers_r006(self) -> None:
        ctx = _ctx_with(
            {
                "A": _task("A", blocks=["B"]),
                "B": _task("B", blocks=["A"], blocked_by=["A"]),
            }
        )
        snap = _snapshot(ctx)
        assert "A" in snap.cycle_task_ids
        response = Z3SolverAdapter().solve(_req(snap, target="A", status="in_progress"))
        assert response.result == "fail"
        assert response.violated_rule == "R-006"

    def test_strict_acceptance_requires_proof(self) -> None:
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    status="in_progress",
                    metadata={"lkb": {"strict_acceptance": True}},
                ),
            }
        )
        snap = _snapshot(ctx)
        response = Z3SolverAdapter().solve(
            _req(snap, target="A", status="completed", strict=True, proof=False)
        )
        assert response.result == "fail"
        assert response.violated_rule == "R-005"

    def test_strict_acceptance_with_proof_passes(self) -> None:
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    status="in_progress",
                    metadata={
                        "lkb": {
                            "strict_acceptance": True,
                            "acceptance_proof": "hash-of-evidence",
                        }
                    },
                ),
            }
        )
        snap = _snapshot(ctx)
        response = Z3SolverAdapter().solve(
            _req(snap, target="A", status="completed", strict=True, proof=True)
        )
        assert response.result == "pass"

    def test_completed_to_pending_reopens(self) -> None:
        ctx = _ctx_with({"A": _task("A", status="completed")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="pending"))
        assert response.result == "pass"

    def test_completed_to_in_progress_reopens(self) -> None:
        ctx = _ctx_with({"A": _task("A", status="completed")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        assert response.result == "pass"


# ---------------------------------------------------------------------------
# Query completeness guards
# ---------------------------------------------------------------------------


class TestQueryGuards:
    def test_missing_target_returns_unknown(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        request = SolverRequest(snapshot=_snapshot(ctx), target_status="pending")
        response = Z3SolverAdapter().solve(request)
        assert response.result == "unknown"
        assert response.error_info == {"reason": "incomplete_query"}

    def test_missing_status_returns_unknown(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        request = SolverRequest(snapshot=_snapshot(ctx), target_task_id="A")
        response = Z3SolverAdapter().solve(request)
        assert response.result == "unknown"
        assert response.error_info == {"reason": "incomplete_query"}

    def test_unknown_target_id_denied(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="Z", status="pending"))
        assert response.result == "fail"
        assert response.violated_rule == "LKB-TRANSITION-001"

    def test_delete_status_skipped(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="deleted"))
        assert response.result == "unknown"
        assert response.error_info == {"reason": "unsupported_status"}

    def test_unsupported_status_returns_unknown(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="archived"))
        assert response.result == "unknown"
        assert response.error_info == {"reason": "unsupported_status"}


# ---------------------------------------------------------------------------
# Aggregation with the pipeline
# ---------------------------------------------------------------------------


class _AlwaysPassAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return "always-pass"

    @property
    def version(self) -> str:
        return "0.0.0"

    def available(self) -> bool:
        return True

    def solve(self, request: SolverRequest, *, timeout_seconds: float = 30.0) -> SolverResponse:
        return SolverResponse(result="pass")


class TestPipelineIntegration:
    def test_layer1_plus_z3_agrees_on_ready(self) -> None:
        ctx = _ctx_with({"A": _task("A")})
        pipeline = SolverPipeline([Layer1SolverAdapter(), Z3SolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target="A", status="in_progress"),
            proposal_id="P-ready",
        )
        assert run.result == "pass"
        engines = {r["adapter"] for r in run.solver_results}
        assert engines == {"layer1-python", "smt-z3"}

    def test_any_fail_means_overall_fail(self) -> None:
        ctx = _ctx_with(
            {
                "A": _task("A"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        pipeline = SolverPipeline([Layer1SolverAdapter(), Z3SolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target="B", status="in_progress"),
            proposal_id="P-block",
        )
        assert run.result == "fail"
        assert all(r["result"] == "fail" for r in run.solver_results)

    def test_strict_acceptance_blocked_by_z3_only(self) -> None:
        # Skip Layer 1 by registering only Z3 — verifies Z3 alone catches R-005.
        # The service-level ``issues`` list is populated by Service, not by the
        # adapter; here we only verify the solver response payload.
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    status="in_progress",
                    metadata={"lkb": {"strict_acceptance": True}},
                ),
            }
        )
        pipeline = SolverPipeline([Z3SolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target="A", status="completed", strict=True, proof=False),
            proposal_id="P-strict",
        )
        assert run.result == "fail"
        assert run.engine == "smt-z3"
        z3_entry = next(r for r in run.solver_results if r["adapter"] == "smt-z3")
        assert z3_entry["result"] == "fail"
        assert z3_entry["violatedRule"] == "R-005"


# ---------------------------------------------------------------------------
# Service-level smoke test
# ---------------------------------------------------------------------------


class TestServiceWithZ3Pipeline:
    def test_service_can_swap_in_z3_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ctx = _ctx_with(
            {
                "A": _task("A"),
                "B": _task("B", blocked_by=["A"]),
            }
        )
        service = LogicalKanbanService()
        service.pipeline = SolverPipeline([Layer1SolverAdapter(), Z3SolverAdapter()])
        snapshot = _snapshot(ctx)
        # Bootstrap the runtime cache to honor the new pipeline.
        from clawcodex_ext.logical_kanban.runtime import get_logical_kanban

        runtime = get_logical_kanban(ctx)
        runtime._snapshot_cache_key = None
        change = ProposedChange(
            kind="transition_status",
            payload={"taskId": "B", "status": "in_progress"},
        )
        _proposal, validation, commit = service.run(change, ctx)
        assert validation.result == "fail"
        assert commit.committed is False
        adapter_names = {r["adapter"] for r in validation.solver_results}
        assert {"layer1-python", "smt-z3"}.issubset(adapter_names)


# ---------------------------------------------------------------------------
# F-139 sanitisation
# ---------------------------------------------------------------------------


class TestSecuritySanitisation:
    def test_encode_solver_literal_rejects_unsafe_chars(self) -> None:
        escaped = encode_solver_literal("<script>alert(1)</script>")
        assert "<" not in escaped and ">" not in escaped
        assert escaped.endswith(tuple(re.findall(r"_h[0-9a-f]{4}$", escaped))[0])

    def test_fact_parser_handles_basic_predicates(self) -> None:
        assert _parse_fact("Task(A)") == ("Task", ("A",))
        assert _parse_fact("Status(A, pending)") == ("Status", ("A", "pending"))
        assert _parse_fact("Blocks(A, B)") == ("Blocks", ("A", "B"))

    def test_fact_parser_handles_quoted_arguments(self) -> None:
        assert _parse_fact('Title(todo:0, "hello")') == ("Title", ("todo:0", "hello"))

    def test_fact_parser_returns_none_for_garbage(self) -> None:
        assert _parse_fact("not a fact") is None
        assert _parse_fact(123) is None  # type: ignore[arg-type]

    def test_hostile_subject_does_not_crash(self) -> None:
        # The subject text flows through ``encode_solver_literal`` so the
        # SMT identifier is generated even for adversarial content.
        ctx = _ctx_with(
            {
                "A": _task(
                    "A",
                    subject='"; (assert (not Task))',
                    description="\\x00\\n",
                ),
            }
        )
        response = Z3SolverAdapter().solve(_req(_snapshot(ctx), target="A", status="in_progress"))
        assert response.result == "pass"
