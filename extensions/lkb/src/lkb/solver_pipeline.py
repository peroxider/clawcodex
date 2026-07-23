"""Solver pipeline for Logical Kanban (F-138).

The pipeline runs a configurable set of :class:`SolverAdapter` instances for a
single :class:`SolverRequest`, enforces per-adapter timeouts, and aggregates the
canonical responses into one :class:`ValidationRun`.

Aggregation is conservative ("deny by default"):

* any adapter reports ``fail``      → overall ``fail``
* any adapter reports ``unknown``,
  ``timeout`` or ``error``         → overall ``unknown``
* all adapters report ``pass``      → overall ``pass``

This matches the policy in ``docs/feature_plan/logical_kanban_v3_spec.md``
section 10.1/10.7.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from . import metrics
from .solver_adapter import SolverAdapter, SolverRequest, SolverResponse
from .types import ValidationIssue, ValidationRun

if TYPE_CHECKING:
    from .types import FactsSnapshot

class SolverPipeline:
    """Run a set of solver adapters and aggregate their responses."""

    def __init__(
        self,
        adapters: tuple[SolverAdapter, ...] | list[SolverAdapter] | None = None,
    ) -> None:
        if adapters is None:
            from .solver_adapter import default_adapters

            adapters = default_adapters()
        self.adapters: tuple[SolverAdapter, ...] = tuple(adapters)

    def validate(
        self,
        request: SolverRequest,
        *,
        proposal_id: str,
        task_id: str | None = None,
        input_facts_hash: str = "",
        ruleset_hash: str = "",
        snapshot_hash: str = "",
        timeout_seconds: float = 30.0,
        requested_by: str = "system",
    ) -> ValidationRun:
        """Run every configured adapter and return a single ``ValidationRun``."""
        if not self.adapters:
            return self._error_run(
                proposal_id=proposal_id,
                task_id=task_id,
                input_facts_hash=input_facts_hash,
                ruleset_hash=ruleset_hash,
                snapshot_hash=snapshot_hash,
                message="No solver adapters are configured.",
                requested_by=requested_by,
            )

        start = time.perf_counter()
        results: list[dict[str, Any]] = []
        any_fail = False
        any_uncertain = False

        for adapter in self.adapters:
            adapter_start = time.perf_counter()
            response = self._run_adapter(adapter, request, timeout_seconds)
            adapter_duration_ms = int((time.perf_counter() - adapter_start) * 1000)
            results.append(
                {
                    "adapter": adapter.name,
                    "version": adapter.version,
                    "available": adapter.available(),
                    "durationMs": adapter_duration_ms,
                    **response.to_dict(),
                }
            )
            if response.result == "fail":
                any_fail = True
            elif response.result in ("unknown", "timeout", "error"):
                any_uncertain = True
            metrics.record_adapter_result(
                adapter=adapter.name,
                result=response.result,
                duration_ms=adapter_duration_ms,
                timeout_seconds=timeout_seconds,
                task_id=request.target_task_id,
            )
            if response.result == "timeout":
                metrics.record_timeout(
                    adapter=adapter.name,
                    timeout_seconds=timeout_seconds,
                    task_id=request.target_task_id,
                )

        duration_ms = int((time.perf_counter() - start) * 1000)

        # Conservative aggregation.
        if any_fail:
            overall_result = "fail"
        elif any_uncertain:
            overall_result = "unknown"
        else:
            overall_result = "pass"

        primary = self.adapters[0]
        derived_facts, proof_trace, violated_rule, message, cycle_tasks = _merge_responses(
            [r for r in results if r.get("result") in ("pass", "fail")]
        )
        counterexample = _first_counterexample(results)

        return ValidationRun(
            validation_run_id=_new_id("V-"),
            proposal_id=proposal_id,
            task_id=task_id,
            input_facts_hash=input_facts_hash,
            ruleset_hash=ruleset_hash,
            snapshot_hash=snapshot_hash,
            engine=primary.name,
            engine_version=primary.version,
            result=overall_result,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            derived_facts=derived_facts,
            proof_trace=proof_trace,
            counterexample=counterexample,
            repair_suggestions=(),
            issues=(),
            created_at=datetime.now(timezone.utc).isoformat(),
            requested_by=requested_by,
            solver_results=tuple(results),
        )

    def _run_adapter(
        self,
        adapter: SolverAdapter,
        request: SolverRequest,
        timeout_seconds: float,
    ) -> SolverResponse:
        """Invoke ``adapter.solve`` with a timeout, catching all failures."""
        if not adapter.available():
            return SolverResponse(
                result="unknown",
                message=f"{adapter.name} is not available.",
                error_info={"reason": "engine_unavailable"},
            )

        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _target() -> None:
            try:
                response = adapter.solve(
                    request,
                    timeout_seconds=timeout_seconds,
                )
                result_queue.put(("response", response))
            except Exception as exc:  # noqa: BLE001
                result_queue.put(("exception", exc))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=timeout_seconds)

        if thread.is_alive():
            return SolverResponse(
                result="timeout",
                message=f"{adapter.name} exceeded the {timeout_seconds}s timeout.",
                error_info={"reason": "timeout", "timeout_seconds": timeout_seconds},
            )

        try:
            kind, value = result_queue.get(block=False)
        except queue.Empty:
            return SolverResponse(
                result="timeout",
                message=f"{adapter.name} exceeded the {timeout_seconds}s timeout.",
                error_info={"reason": "timeout", "timeout_seconds": timeout_seconds},
            )

        if kind == "exception":
            exc = value
            return SolverResponse(
                result="error",
                message=f"{adapter.name} raised {type(exc).__name__}: {exc}",
                error_info={
                    "reason": "exception",
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                },
            )
        return value

    def _error_run(
        self,
        *,
        proposal_id: str,
        task_id: str | None,
        input_facts_hash: str,
        ruleset_hash: str,
        snapshot_hash: str,
        message: str,
        requested_by: str,
    ) -> ValidationRun:
        return ValidationRun(
            validation_run_id=_new_id("V-"),
            proposal_id=proposal_id,
            task_id=task_id,
            input_facts_hash=input_facts_hash,
            ruleset_hash=ruleset_hash,
            snapshot_hash=snapshot_hash,
            engine="solver-pipeline",
            engine_version="",
            result="error",
            duration_ms=0,
            derived_facts=(),
            proof_trace=(),
            repair_suggestions=(),
            issues=(
                ValidationIssue(
                    code="solver_pipeline_empty",
                    message=message,
                    rule="LKB-SOLVER-001",
                    task_id=task_id,
                ),
            ),
            created_at=datetime.now(timezone.utc).isoformat(),
            requested_by=requested_by,
            solver_results=(),
        )

def _merge_responses(
    responses: list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...], str | None, str, tuple[str, ...]]:
    """Merge deterministic responses for inclusion in the ``ValidationRun``.

    The returned values are used as defaults; service-level callers still add
    their own human-readable issues and repair suggestions.
    """
    facts: set[str] = set()
    traces: list[dict[str, Any]] = []
    seen_traces: set[tuple[str, str, tuple[str, ...]]] = set()
    violated_rule: str | None = None
    message = ""
    cycle_tasks: set[str] = set()

    for response in responses:
        facts.update(response.get("derivedFacts", []))
        if response.get("result") == "fail":
            if violated_rule is None:
                violated_rule = response.get("violatedRule")
            if not message:
                message = response.get("message", "")
            cycle_tasks.update(response.get("cycleTasks", []))
        for trace in response.get("proofTrace", []):
            premises = tuple(trace.get("premises", []))
            key = (trace.get("rule", ""), trace.get("conclusion", ""), premises)
            if key in seen_traces:
                continue
            seen_traces.add(key)
            traces.append(dict(trace))

    return tuple(sorted(facts)), tuple(traces), violated_rule, message, tuple(sorted(cycle_tasks))

def _first_counterexample(responses: list[dict[str, Any]]) -> dict[str, Any] | None:
    for response in responses:
        counterexample = response.get("counterexample")
        if isinstance(counterexample, dict):
            return counterexample
    return None

def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"

__all__ = ["SolverPipeline"]
