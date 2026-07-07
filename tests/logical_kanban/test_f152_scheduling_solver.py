"""Tests for F-152 Bounded Scheduling Solver (OR-Tools CP-SAT).

These tests cover the public SchedulingSolver API, the dataclass
contract, the integration with :class:`TaskDecomposer`, and the
graceful-degradation path when OR-Tools is not installed.

The tests are organised as:

* ``TestDataclasses`` — constructor validation for Resource /
  SchedulingTask.
* ``TestSchedulingSolverBasic`` — happy-path scheduling on small
  problems (2 tasks / 1 resource, 5 tasks / 2 resources).
* ``TestSchedulingSolverConstraints`` — no-overlap, cumulative,
  time-window, predecessor, and skill constraints.
* ``TestSchedulingSolverObjectives`` — makespan / weighted_completion /
  resource_level.
* ``TestSchedulingSolverEdgeCases`` — timeout, infeasibility, empty
  input, fallback when ortools is missing.
* ``TestValidateSchedule`` — the defensive schedule validator.
* ``TestTaskDecomposerIntegration`` — plan-level scheduling pass via
  ``scheduling_constraints``.
* ``TestGoldenSet`` — the 5 real-world scenarios called out in the
  F-152 acceptance criteria.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (
    DecompositionPlan,
    Resource,
    Schedule,
    SchedulingError,
    SchedulingSolver,
    SchedulingTask,
    SchedulingUnavailable,
    TaskDecomposer,
    TaskDecompositionError,
    validate_schedule,
)
from clawcodex_ext.logical_kanban.scheduling_solver import (
    OPTIMAL,  # re-exported for sanity-check assertions
)
from clawcodex_ext.providers.base import BaseProvider, ChatResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ortools_available() -> bool:
    """True if the ``[scheduling]`` extra is installed in this env."""
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except ImportError:
        return False
    return True


_ORT = pytest.mark.skipif(
    not _ortools_available(), reason="ortools (scheduling extra) not installed"
)


def _provider(response: dict[str, Any]) -> BaseProvider:
    """Build a BaseProvider stub that returns ``response`` once."""

    class _Stub(BaseProvider):
        def __init__(self) -> None:
            super().__init__(api_key="test")

        def chat(
            self,
            messages: list[Any],
            tools: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> ChatResponse:
            return ChatResponse(
                content=json.dumps(response),
                model="stub",
                usage={"input_tokens": 1, "output_tokens": 1},
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

    return _Stub()


def _default_plan() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "proposedTaskId": "tmp-a",
                "subject": "Set up scaffold",
                "description": "Init project",
                "activeForm": "Setting up",
                "acceptanceCriteria": ["ok"],
                "blockedBy": [],
                "lkbMetadata": {
                    "assertions": [],
                    "acceptance_proof": "ok",
                    "assumptions": [],
                    "strict_acceptance": False,
                    "duration": 2,
                },
            },
            {
                "proposedTaskId": "tmp-b",
                "subject": "Write code",
                "description": "Implement feature",
                "activeForm": "Writing",
                "acceptanceCriteria": ["ok"],
                "blockedBy": ["tmp-a"],
                "lkbMetadata": {
                    "assertions": [],
                    "acceptance_proof": "ok",
                    "assumptions": [],
                    "strict_acceptance": False,
                    "duration": 3,
                },
            },
            {
                "proposedTaskId": "tmp-c",
                "subject": "Test",
                "description": "Run tests",
                "activeForm": "Testing",
                "acceptanceCriteria": ["ok"],
                "blockedBy": ["tmp-b"],
                "lkbMetadata": {
                    "assertions": [],
                    "acceptance_proof": "ok",
                    "assumptions": [],
                    "strict_acceptance": False,
                    "duration": 2,
                },
            },
        ],
        "dependencies": [["tmp-a", "tmp-b"], ["tmp-b", "tmp-c"]],
        "assumptions": [],
    }


# ---------------------------------------------------------------------------
# TestDataclasses — constructor validation
# ---------------------------------------------------------------------------


class TestDataclasses:
    """Resource / SchedulingTask / Schedule dataclass contract."""

    def test_resource_default_capacity(self) -> None:
        r = Resource(resource_id="alice")
        assert r.capacity == 1
        assert r.availability == ()
        assert r.skills == frozenset()

    def test_resource_rejects_empty_id(self) -> None:
        with pytest.raises(SchedulingError):
            Resource(resource_id="")

    def test_resource_rejects_invalid_capacity(self) -> None:
        with pytest.raises(SchedulingError):
            Resource(resource_id="r1", capacity=0)
        with pytest.raises(SchedulingError):
            Resource(resource_id="r1", capacity=-1)

    def test_resource_rejects_bad_availability(self) -> None:
        with pytest.raises(SchedulingError):
            Resource(resource_id="r1", availability=((0, 0),))
        with pytest.raises(SchedulingError):
            Resource(resource_id="r1", availability=((5, 2),))

    def test_resource_rejects_bad_skill(self) -> None:
        with pytest.raises(SchedulingError):
            Resource(resource_id="r1", skills=frozenset({""}))  # type: ignore[arg-type]

    def test_task_default_values(self) -> None:
        t = SchedulingTask(task_id="a", duration=5)
        assert t.earliest_start is None
        assert t.latest_finish is None
        assert t.required_skills == frozenset()
        assert t.predecessors == ()
        assert t.priority == 1

    def test_task_rejects_empty_id(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="", duration=1)

    def test_task_rejects_non_positive_duration(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=0)
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=-1)

    def test_task_rejects_impossible_time_window(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=5, earliest_start=0, latest_finish=4)

    def test_task_rejects_negative_earliest_start(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=1, earliest_start=-1)

    def test_task_rejects_negative_latest_finish(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=1, latest_finish=-1)

    def test_task_rejects_bad_predecessor(self) -> None:
        with pytest.raises(SchedulingError):
            SchedulingTask(task_id="a", duration=1, predecessors=("",))  # type: ignore[arg-type]

    def test_schedule_to_dict_round_trip(self) -> None:
        s = Schedule(
            assignments={"a": (0, 3, "r1")},
            makespan=3,
            objective_value=3,
            status="optimal",
            objective="makespan",
        )
        d = s.to_dict()
        assert d["status"] == "optimal"
        assert d["objective"] == "makespan"
        assert d["makespan"] == 3
        assert d["assignments"]["a"] == {"start": 0, "end": 3, "resourceId": "r1"}

    def test_resource_to_dict_and_from_dict_round_trip(self) -> None:
        r = Resource(
            resource_id="dev1",
            capacity=2,
            availability=((0, 10), (20, 30)),
            skills=frozenset({"python", "go"}),
        )
        d = r.to_dict()
        assert d["resourceId"] == "dev1"
        assert d["capacity"] == 2
        assert d["availability"] == [[0, 10], [20, 30]]
        assert set(d["skills"]) == {"python", "go"}
        # Round-trip: from_dict(to_dict(...)) == original.
        r2 = Resource.from_dict(d)
        assert r2.resource_id == r.resource_id
        assert r2.capacity == r.capacity
        assert r2.availability == r.availability
        assert r2.skills == r.skills

    def test_resource_from_dict_accepts_snake_case_keys(self) -> None:
        r = Resource.from_dict({"resource_id": "dev2", "capacity": 3})
        assert r.resource_id == "dev2"
        assert r.capacity == 3

    def test_resource_from_dict_defaults(self) -> None:
        r = Resource.from_dict({"resourceId": "dev3"})
        assert r.capacity == 1
        assert r.availability == ()
        assert r.skills == frozenset()

    def test_resource_from_dict_rejects_missing_id(self) -> None:
        with pytest.raises(SchedulingError):
            Resource.from_dict({"capacity": 1})

    def test_lkb_metadata_keys_includes_scheduling_fields(self) -> None:
        """F-152: ``scheduling_required``, ``duration``, ``earliest_start``
        are accepted as LKB metadata so the LLM can flag scheduling intent.
        """
        # We assert on the module-level set so future F-N additions are
        # visible in code review.
        from clawcodex_ext.logical_kanban.decomposer import _LKB_METADATA_KEYS as keys

        assert "scheduling_required" in keys
        assert "duration" in keys
        assert "earliest_start" in keys


# ---------------------------------------------------------------------------
# TestSchedulingSolverBasic
# ---------------------------------------------------------------------------


@_ORT
class TestSchedulingSolverBasic:
    """Happy-path scheduling on small problems."""

    def test_two_tasks_one_resource(self) -> None:
        solver = SchedulingSolver()
        t1 = SchedulingTask(task_id="a", duration=5)
        t2 = SchedulingTask(task_id="b", duration=3)
        alice = Resource(resource_id="alice")
        result = solver.schedule([t1, t2], [alice], horizon=20)
        assert result.status == "optimal"
        assert result.makespan == 8
        # tasks run sequentially on the single resource
        assert {tid: a[2] for tid, a in result.assignments.items()} == {
            "a": "alice",
            "b": "alice",
        }

    def test_five_tasks_two_resources(self) -> None:
        """The acceptance-criteria scenario: 5 tasks 2 resources with a
        fork/join shape — verifies the critical path is preserved.
        """
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="a", duration=2),
            SchedulingTask(task_id="b", duration=3, predecessors=("a",)),
            SchedulingTask(task_id="c", duration=4, predecessors=("b",)),
            SchedulingTask(task_id="d", duration=2, predecessors=("a",)),
            SchedulingTask(task_id="e", duration=3, predecessors=("c", "d")),
        )
        resources = (Resource(resource_id="r1"), Resource(resource_id="r2"))
        result = solver.schedule(tasks, resources, horizon=20)
        assert result.status == "optimal"
        # Critical path: a(2) -> b(3) -> c(4) -> e(3) = 12
        assert result.makespan == 12
        # d runs in parallel to b: a(2) -> d(2)
        d = result.assignments["d"]
        assert d[0] >= 2 and d[1] <= 6

    def test_empty_task_list_is_trivially_optimal(self) -> None:
        solver = SchedulingSolver()
        result = solver.schedule([], [Resource(resource_id="r1")], horizon=10)
        assert result.status == "optimal"
        assert result.makespan == 0
        assert result.assignments == {}

    def test_empty_task_list_with_no_resources(self) -> None:
        solver = SchedulingSolver()
        result = solver.schedule([], [], horizon=10)
        assert result.status == "optimal"
        assert result.makespan == 0

    def test_solver_constructor_raises_when_ortools_missing(self) -> None:
        # Temporarily hide cp_model in the module under test.
        from clawcodex_ext.logical_kanban import scheduling_solver as mod

        saved = (mod.cp_model, mod.CpModel, mod.CpSolver)
        mod.cp_model = None
        mod.CpModel = None
        mod.CpSolver = None
        try:
            with pytest.raises(SchedulingUnavailable):
                SchedulingSolver()
        finally:
            mod.cp_model, mod.CpModel, mod.CpSolver = saved


# ---------------------------------------------------------------------------
# TestSchedulingSolverConstraints
# ---------------------------------------------------------------------------


@_ORT
class TestSchedulingSolverConstraints:
    """Per-constraint-type behaviour."""

    def test_predecessor_chain_preserves_order(self) -> None:
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="a", duration=2),
            SchedulingTask(task_id="b", duration=2, predecessors=("a",)),
            SchedulingTask(task_id="c", duration=2, predecessors=("b",)),
        )
        result = solver.schedule(tasks, [Resource(resource_id="r1")], horizon=20)
        a, b, c = (result.assignments[t] for t in ("a", "b", "c"))
        assert a[1] <= b[0]
        assert b[1] <= c[0]

    def test_unknown_predecessor_raises(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=1, predecessors=("missing",))
        with pytest.raises(SchedulingError):
            solver.schedule([t], [Resource(resource_id="r1")], horizon=10)

    def test_time_window_earliest_start(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=2, earliest_start=5)
        result = solver.schedule([t], [Resource(resource_id="r1")], horizon=20)
        assert result.assignments["a"][0] == 5

    def test_time_window_latest_finish(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=3, latest_finish=10)
        result = solver.schedule([t], [Resource(resource_id="r1")], horizon=20)
        assert result.assignments["a"][1] == 3  # earliest possible

    def test_cumulative_capacity(self) -> None:
        """Pool of 2 — three tasks of duration 3 should finish in 6."""
        solver = SchedulingSolver()
        tasks = tuple(SchedulingTask(task_id=f"t{i}", duration=3) for i in range(3))
        pool = Resource(resource_id="pool", capacity=2)
        result = solver.schedule(tasks, [pool], horizon=20)
        assert result.makespan == 6

    def test_no_overlap_with_capacity_one(self) -> None:
        solver = SchedulingSolver()
        t1 = SchedulingTask(task_id="a", duration=4)
        t2 = SchedulingTask(task_id="b", duration=4)
        result = solver.schedule(
            [t1, t2], [Resource(resource_id="r1", capacity=1)], horizon=20
        )
        a, b = (result.assignments[t] for t in ("a", "b"))
        assert a[1] <= b[0] or b[1] <= a[0]
        assert result.makespan == 8

    def test_skill_matching_routes_to_qualified_resource(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=3, required_skills=frozenset({"python"}))
        result = solver.schedule(
            [t],
            [
                Resource(resource_id="go_dev", skills=frozenset({"go"})),
                Resource(resource_id="py_dev", skills=frozenset({"python"})),
            ],
            horizon=20,
        )
        assert result.assignments["a"][2] == "py_dev"

    def test_skill_infeasible_raises_at_validation(self) -> None:
        """If no resource offers the required skill, the model is
        trivially infeasible — we surface that as a hard error.
        """
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=1, required_skills=frozenset({"rust"}))
        with pytest.raises(SchedulingError):
            solver.schedule([t], [Resource(resource_id="py_dev")], horizon=10)

    def test_availability_window_constrains_task(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=2)
        result = solver.schedule(
            [t], [Resource(resource_id="r1", availability=((5, 10),))], horizon=20
        )
        assert result.assignments["a"][0] >= 5
        assert result.assignments["a"][1] <= 10

    def test_horizon_smaller_than_duration_raises(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=10)
        with pytest.raises(SchedulingError):
            solver.schedule([t], [Resource(resource_id="r1")], horizon=5)

    def test_horizon_zero_raises(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=1)
        with pytest.raises(SchedulingError):
            solver.schedule([t], [Resource(resource_id="r1")], horizon=0)

    def test_duplicate_task_id_raises(self) -> None:
        solver = SchedulingSolver()
        t1 = SchedulingTask(task_id="a", duration=1)
        t2 = SchedulingTask(task_id="a", duration=1)
        with pytest.raises(SchedulingError):
            solver.schedule([t1, t2], [Resource(resource_id="r1")], horizon=10)


# ---------------------------------------------------------------------------
# TestSchedulingSolverObjectives
# ---------------------------------------------------------------------------


@_ORT
class TestSchedulingSolverObjectives:
    """Objective selection shapes the result."""

    def test_makespan_is_default(self) -> None:
        solver = SchedulingSolver()
        tasks = tuple(SchedulingTask(task_id=f"t{i}", duration=2) for i in range(4))
        result = solver.schedule(tasks, [Resource(resource_id="r1")], horizon=20)
        assert result.objective == "makespan"
        assert result.makespan == 8  # 4 * 2 sequential

    def test_weighted_completion_prefers_high_priority_first(self) -> None:
        solver = SchedulingSolver()
        # t_high has priority 10, t_low has priority 1.  The solver
        # should place t_high first so its end is smaller.
        tasks = (
            SchedulingTask(task_id="high", duration=2, priority=10),
            SchedulingTask(task_id="low", duration=2, priority=1),
        )
        result = solver.schedule(
            tasks, [Resource(resource_id="r1")], horizon=20, objective="weighted_completion"
        )
        # high should finish before low
        high = result.assignments["high"]
        low = result.assignments["low"]
        assert high[1] <= low[0]
        # 10*2 + 1*4 = 24
        assert result.objective_value == 24

    def test_resource_level_falls_back_to_makespan(self) -> None:
        """With a single resource the 'resource_level' objective has no
        peak-signal to optimize, so it falls back to makespan and
        echoes the original objective in the returned Schedule.
        """
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="a", duration=2),
            SchedulingTask(task_id="b", duration=2),
        )
        result = solver.schedule(
            tasks,
            [Resource(resource_id="r1")],
            horizon=20,
            objective="resource_level",
        )
        assert result.objective == "resource_level"
        assert result.makespan == 4

    def test_unknown_objective_raises(self) -> None:
        solver = SchedulingSolver()
        with pytest.raises(SchedulingError):
            solver.schedule(
                [SchedulingTask(task_id="a", duration=1)],
                [Resource(resource_id="r1")],
                horizon=10,
                objective="turbo",
            )


# ---------------------------------------------------------------------------
# TestSchedulingSolverEdgeCases
# ---------------------------------------------------------------------------


@_ORT
class TestSchedulingSolverEdgeCases:
    """Infeasibility, timeout, and the (no-ortools) fallback path."""

    def test_infeasible_when_latest_finish_too_tight(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=10, latest_finish=5)
        result = solver.schedule([t], [Resource(resource_id="r1")], horizon=20)
        assert result.status == "infeasible"
        assert result.assignments == {}

    def test_infeasible_tight_horizon(self) -> None:
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="a", duration=3),
            SchedulingTask(task_id="b", duration=3),
        )
        result = solver.schedule(
            tasks, [Resource(resource_id="r1", capacity=1)], horizon=5
        )
        assert result.status == "infeasible"

    def test_timeout_returns_status(self) -> None:
        solver = SchedulingSolver()
        t = SchedulingTask(task_id="a", duration=2)
        result = solver.schedule(
            [t], [Resource(resource_id="r1")], horizon=20, timeout_seconds=0.001
        )
        # Tiny problems usually solve instantly, so this can be
        # "optimal", "feasible", or "timeout" depending on the host.
        # We assert that the call did not raise, and that the status
        # is one of the documented values.
        assert result.status in ("optimal", "feasible", "timeout", "infeasible")

    def test_sla_under_one_second_for_20_tasks_5_resources(self) -> None:
        """F-152 SLA: N≤20 + M≤5 + horizon≤30 days, <1s."""
        import time

        solver = SchedulingSolver()
        tasks = tuple(
            SchedulingTask(
                task_id=f"t{i}",
                duration=2,
                predecessors=(f"t{(i - 1) // 2}",) if i > 0 and i % 2 == 0 else (),
            )
            for i in range(20)
        )
        resources = tuple(Resource(resource_id=f"r{i}") for i in range(5))
        start = time.time()
        result = solver.schedule(tasks, resources, horizon=30, timeout_seconds=5.0)
        elapsed = time.time() - start
        assert result.status in ("optimal", "feasible")
        assert elapsed < 1.0, f"Scheduling took {elapsed:.3f}s, exceeds 1s SLA"

    def test_negative_timeout_seconds_raises(self) -> None:
        solver = SchedulingSolver()
        with pytest.raises(SchedulingError):
            solver.schedule(
                [SchedulingTask(task_id="a", duration=1)],
                [Resource(resource_id="r1")],
                horizon=10,
                timeout_seconds=-1.0,
            )

    def test_fallback_returns_none_when_ortools_missing(self) -> None:
        """``TaskDecomposer._run_scheduling_pass`` is a no-op when OR-Tools
        is unavailable — the plan is still returned without a schedule.
        """
        from clawcodex_ext.logical_kanban import scheduling_solver as mod

        saved = (mod.cp_model, mod.CpModel, mod.CpSolver)
        mod.cp_model = None
        mod.CpModel = None
        mod.CpSolver = None
        try:
            decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
            plan = decomposer.decompose(
                goal="g",
                max_steps=5,
                scheduling_constraints={
                    "resources": [Resource(resource_id="r1")],
                    "horizon": 10,
                },
            )
            assert plan.scheduling_constraints is not None
            assert plan.schedule is None
        finally:
            mod.cp_model, mod.CpModel, mod.CpSolver = saved


# ---------------------------------------------------------------------------
# TestValidateSchedule
# ---------------------------------------------------------------------------


@_ORT
class TestValidateSchedule:
    """Defensive schedule validator."""

    def _build_schedule(self) -> tuple[Schedule, list[SchedulingTask], list[Resource]]:
        tasks = (
            SchedulingTask(task_id="a", duration=3, earliest_start=0, latest_finish=10),
            SchedulingTask(task_id="b", duration=2, earliest_start=3, latest_finish=10, predecessors=("a",)),
        )
        resources = (Resource(resource_id="alice", skills=frozenset({"python"})),)
        schedule = Schedule(
            assignments={"a": (0, 3, "alice"), "b": (3, 5, "alice")},
            makespan=5,
            objective_value=5,
            status="optimal",
        )
        return schedule, tasks, resources

    def test_valid_schedule_passes(self) -> None:
        schedule, tasks, resources = self._build_schedule()
        issues = validate_schedule(
            schedule, tasks, resources, dependencies=[("a", "b")]
        )
        assert issues == []

    def test_violated_predecessor_detected(self) -> None:
        schedule, tasks, resources = self._build_schedule()
        # b starts before a ends
        schedule = Schedule(
            assignments={"a": (0, 3, "alice"), "b": (2, 5, "alice")},
            makespan=5,
            objective_value=5,
            status="optimal",
        )
        issues = validate_schedule(
            schedule, tasks, resources, dependencies=[("a", "b")]
        )
        assert any("Dependency violated" in i for i in issues)

    def test_wrong_length_detected(self) -> None:
        schedule, tasks, resources = self._build_schedule()
        schedule = Schedule(
            assignments={"a": (0, 5, "alice"), "b": (5, 7, "alice")},  # a: length 5 != 3
            makespan=7,
            objective_value=7,
            status="optimal",
        )
        issues = validate_schedule(
            schedule, tasks, resources, dependencies=[("a", "b")]
        )
        assert any("declared duration" in i for i in issues)

    def test_unknown_resource_detected(self) -> None:
        schedule, tasks, resources = self._build_schedule()
        schedule = Schedule(
            assignments={"a": (0, 3, "ghost"), "b": (3, 5, "ghost")},
            makespan=5,
            objective_value=5,
            status="optimal",
        )
        issues = validate_schedule(
            schedule, tasks, resources, dependencies=[("a", "b")]
        )
        assert any("unknown resource" in i for i in issues)

    def test_skill_mismatch_detected(self) -> None:
        schedule, tasks, resources = self._build_schedule()
        # Make tasks require 'go' but resource only has 'python'
        bad_tasks = (
            SchedulingTask(task_id="a", duration=3, required_skills=frozenset({"go"})),
            SchedulingTask(task_id="b", duration=2, predecessors=("a",), required_skills=frozenset({"go"})),
        )
        schedule = Schedule(
            assignments={"a": (0, 3, "alice"), "b": (3, 5, "alice")},
            makespan=5,
            objective_value=5,
            status="optimal",
        )
        issues = validate_schedule(
            schedule, bad_tasks, resources, dependencies=[("a", "b")]
        )
        assert any("needs" in i and "go" in i for i in issues)


# ---------------------------------------------------------------------------
# TestTaskDecomposerIntegration
# ---------------------------------------------------------------------------


@_ORT
class TestTaskDecomposerIntegration:
    """End-to-end: ``decompose(scheduling_constraints=...)`` populates the plan."""

    def test_decompose_without_scheduling_returns_no_schedule(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(goal="g", max_steps=5)
        assert isinstance(plan, DecompositionPlan)
        assert plan.schedule is None
        assert plan.scheduling_constraints is None

    def test_decompose_with_scheduling_populates_schedule(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={
                "resources": [Resource(resource_id="r1")],
                "horizon": 30,
                "objective": "makespan",
            },
        )
        assert plan.scheduling_constraints is not None
        assert plan.schedule is not None
        assert plan.schedule.status in ("optimal", "feasible")
        assert plan.schedule.makespan >= 7  # a(2)+b(3)+c(2) on one resource

    def test_to_dict_includes_scheduling_fields(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={
                "resources": [Resource(resource_id="r1")],
                "horizon": 30,
            },
        )
        d = plan.to_dict()
        assert "schedule" in d
        assert "schedulingConstraints" in d
        if plan.schedule is not None:
            assert d["schedule"] is not None
            assert d["schedulingConstraints"] is not None

    def test_to_dict_serializes_none_when_no_scheduling(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(goal="g", max_steps=5)
        d = plan.to_dict()
        assert d["schedule"] is None
        assert d["schedulingConstraints"] is None

    def test_decompose_rejects_non_dict_scheduling_constraints(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        with pytest.raises(ValueError):
            decomposer.decompose(
                goal="g", max_steps=5, scheduling_constraints="bad"  # type: ignore[arg-type]
            )

    def test_decompose_with_empty_resources_does_not_schedule(self) -> None:
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={"resources": [], "horizon": 10},
        )
        # Empty resources is treated as a no-op so the rest of the
        # plan is still usable.
        assert plan.schedule is None
        assert plan.scheduling_constraints is not None

    def test_tool_output_includes_schedule_field(self) -> None:
        from clawcodex_ext.tool_system.context import ToolContext
        from pathlib import Path
        from clawcodex_ext.tool_system.tools.task_decompose import _task_decompose_call

        ctx = ToolContext(workspace_root=Path("."), session_id="test")
        ctx._active_provider = _provider(_default_plan())  # type: ignore[attr-defined]
        result = _task_decompose_call(
            {
                "goal": "g",
                "max_steps": 5,
                "scheduling_constraints": {
                    "resources": [Resource(resource_id="r1")],
                    "horizon": 30,
                },
            },
            ctx,
        )
        assert result.is_error is False
        assert "schedule" in result.output
        assert "schedulingConstraints" in result.output

    def test_tool_rejects_non_dict_scheduling_constraints(self) -> None:
        from clawcodex_ext.tool_system.context import ToolContext
        from clawcodex_ext.tool_system.errors import ToolInputError
        from pathlib import Path
        from clawcodex_ext.tool_system.tools.task_decompose import _task_decompose_call

        ctx = ToolContext(workspace_root=Path("."), session_id="test")
        with pytest.raises(ToolInputError):
            _task_decompose_call(
                {"goal": "g", "scheduling_constraints": "bad"},
                ctx,
            )

    def test_dict_resources_are_converted_by_scheduling_pass(self) -> None:
        """Dict resources (the common LLM tool path) convert to Resource."""
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={
                "resources": [
                    {"resourceId": "r1", "capacity": 1, "skills": ["python"]},
                ],
                "horizon": 30,
            },
        )
        assert plan.schedule is not None
        assert plan.schedule.status in ("optimal", "feasible")

    def test_deadline_alias_for_horizon(self) -> None:
        """``deadline`` is accepted as an alias for ``horizon``."""
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={
                "resources": [Resource(resource_id="r1")],
                "deadline": 30,
            },
        )
        assert plan.schedule is not None
        assert plan.schedule.status in ("optimal", "feasible")

    def test_to_dict_serializes_resource_objects(self) -> None:
        """``schedulingConstraints`` in the dict output must be JSON-safe."""
        decomposer = TaskDecomposer(llm_provider=_provider(_default_plan()))
        plan = decomposer.decompose(
            goal="g",
            max_steps=5,
            scheduling_constraints={
                "resources": [Resource(resource_id="r1")],
                "horizon": 30,
            },
        )
        d = plan.to_dict()
        constraints = d.get("schedulingConstraints")
        assert constraints is not None
        raw_resources = constraints.get("resources")
        assert raw_resources is not None
        for res in raw_resources:
            assert isinstance(res, dict), f"expected dict, got {type(res)}"
            assert "resourceId" in res


# ---------------------------------------------------------------------------
# TestGoldenSet — the 5 real-world scenarios from the F-152 acceptance list
# ---------------------------------------------------------------------------


@_ORT
class TestGoldenSet:
    """Five realistic scheduling scenarios.

    1. **5 migration tasks × 2 DBAs × 1 week** — the literal example
       from the F-152 feature plan.
    2. **2 reviewers × 1 week** — three PRs of varying length.
    3. **Single engineer, three independent fixes** — fully parallel,
       tight horizon.
    4. **Resource with availability windows** — one resource only
       available in the afternoon.
    5. **Mixed skills** — engineer pool with python + go coverage.
    """

    def test_golden_1_dba_migration(self) -> None:
        solver = SchedulingSolver()
        # 5 migration tasks, 2 DBAs, 1 week (168 hours assumed)
        tasks = tuple(
            SchedulingTask(task_id=f"mig-{i}", duration=20, required_skills=frozenset({"dba"}))
            for i in range(5)
        )
        dba_pool = (
            Resource(resource_id="alice", skills=frozenset({"dba"})),
            Resource(resource_id="bob", skills=frozenset({"dba"})),
        )
        result = solver.schedule(tasks, dba_pool, horizon=168, objective="makespan")
        assert result.status in ("optimal", "feasible")
        # With 2 DBAs the makespan should be well below 100
        assert result.makespan <= 60

    def test_golden_2_pr_reviews(self) -> None:
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="pr-1", duration=4),
            SchedulingTask(task_id="pr-2", duration=6),
            SchedulingTask(task_id="pr-3", duration=2),
        )
        reviewers = (
            Resource(resource_id="rev-1"),
            Resource(resource_id="rev-2"),
        )
        result = solver.schedule(tasks, reviewers, horizon=40, objective="makespan")
        assert result.status in ("optimal", "feasible")
        # pr-2 is the longest, expect makespan at least 6
        assert result.makespan >= 6

    def test_golden_3_three_fixes_one_engineer(self) -> None:
        solver = SchedulingSolver()
        tasks = tuple(
            SchedulingTask(task_id=f"fix-{i}", duration=2) for i in range(3)
        )
        result = solver.schedule(
            tasks, [Resource(resource_id="eng-1")], horizon=20
        )
        assert result.makespan == 6
        # Verify the three intervals are non-overlapping on the same resource.
        intervals = sorted(
            (result.assignments[f"fix-{i}"][0], result.assignments[f"fix-{i}"][1])
            for i in range(3)
        )
        assert intervals[0][1] == intervals[1][0]
        assert intervals[1][1] == intervals[2][0]
        # And the union covers [0, 6] with no gaps.
        assert intervals[0][0] == 0
        assert intervals[-1][1] == 6

    def test_golden_4_afternoon_only_resource(self) -> None:
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(task_id="morning-1", duration=2),
            SchedulingTask(task_id="afternoon-1", duration=3),
        )
        result = solver.schedule(
            tasks,
            [Resource(resource_id="alice", availability=((12, 18),))],
            horizon=24,
        )
        assert result.status in ("optimal", "feasible")
        # Both tasks must fall inside [12, 18]
        for tid in ("morning-1", "afternoon-1"):
            s, e, _ = result.assignments[tid]
            assert s >= 12 and e <= 18

    def test_golden_5_mixed_skills(self) -> None:
        solver = SchedulingSolver()
        tasks = (
            SchedulingTask(
                task_id="py-job", duration=4, required_skills=frozenset({"python"})
            ),
            SchedulingTask(
                task_id="go-job", duration=3, required_skills=frozenset({"go"})
            ),
            SchedulingTask(
                task_id="full-stack",
                duration=5,
                required_skills=frozenset({"python", "go"}),
            ),
        )
        resources = (
            Resource(resource_id="py-eng", skills=frozenset({"python"})),
            Resource(resource_id="go-eng", skills=frozenset({"go"})),
            Resource(resource_id="fullstack", skills=frozenset({"python", "go"})),
        )
        result = solver.schedule(tasks, resources, horizon=30, objective="makespan")
        assert result.status in ("optimal", "feasible")
        # full-stack can only be on 'fullstack' or on whoever has both
        assigned = result.assignments["full-stack"][2]
        assert assigned == "fullstack" or {"python", "go"}.issubset(
            next(r.skills for r in resources if r.resource_id == assigned)
        )
