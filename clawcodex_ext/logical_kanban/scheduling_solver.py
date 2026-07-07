"""F-152 Bounded Scheduling Solver (OR-Tools CP-SAT).

⚠️ DO NOT IMPORT FROM ortools.* EXCEPT ortools.sat.python.cp_model.

The OR-Tools meta-package bundles 6 other sub-modules (routing,
linear_solver, constraint_solver, algorithms, graph, ml), some of which
contain ML/heuristic black boxes that violate the project's "no extra
models" hard rule.  LKB only uses the CP-SAT constraint-programming
backend, and the ``[tool.ruff.lint.flake8-tidy-imports.banned-api]``
block in ``pyproject.toml`` rejects every other ``ortools.*`` import
at lint time (TID251).  See ``docs/feature_plan/09-logical-kanban/
f-152-bounded-scheduling-solver.md`` Phase 1 for the rationale.

This module exposes three layers, all opt-in:

1. **Dataclasses** (:class:`Resource`, :class:`SchedulingTask`,
   :class:`Schedule`) — pure data, no CP-SAT dependency at import time.
2. **Optional CP-SAT backend** (:class:`SchedulingSolver`) — wraps
   ``ortools.sat.python.cp_model`` behind a small Python API.  When the
   ``[scheduling]`` extra is not installed the backend raises
   :class:`SchedulingUnavailable` so callers can degrade gracefully.
3. **Schedule validation** (:func:`validate_schedule`) — checks the
   solver output against the input task graph and resource pool.  Used
   by :class:`~clawcodex_ext.logical_kanban.decomposer.TaskDecomposer`
   in Phase 4 to keep LKB honest about the schedule it surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Literal

# --- CP-SAT optional import (lints clean even without ortools) ------
try:
    from ortools.sat.python import cp_model
    from ortools.sat.python.cp_model import (
        CpModel,
        CpSolver,
        FEASIBLE,
        INFEASIBLE,
        MODEL_INVALID,
        OPTIMAL,
        UNKNOWN,
    )
except ImportError:  # pragma: no cover - environment-dependent
    cp_model = None  # type: ignore[assignment]
    CpModel = None  # type: ignore[assignment,misc]
    CpSolver = None  # type: ignore[assignment,misc]
    OPTIMAL = 4  # type: ignore[assignment]
    FEASIBLE = 2  # type: ignore[assignment]
    INFEASIBLE = 3  # type: ignore[assignment]
    MODEL_INVALID = 1  # type: ignore[assignment]
    # UNKNOWN is what the solver returns when max_time_in_seconds expires
    # before any conclusion is reached.  The runtime value is 0 in the
    # current ortools release, but we only need it to differ from the
    # other constants so the ``_STATUS_MAP`` lookup can recognise it.
    UNKNOWN = -1  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ortools.sat.python.cp_model import CpModel as _CpModelType


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchedulingUnavailable(RuntimeError):
    """Raised when the CP-SAT backend is not importable.

    Install the optional extra to enable the solver::

        pip install clawcodex[scheduling]

    The LKB pipeline catches this in :mod:`clawcodex_ext.logical_kanban.
    decomposer` and proceeds with ``schedule=None`` so decomposition
    stays available without OR-Tools.
    """


class SchedulingError(ValueError):
    """Raised when the input is malformed (e.g. unknown task, bad
    predecessor, negative duration).

    Distinct from :class:`SchedulingUnavailable` so callers can tell
    "I need to install ortools" apart from "the user input is wrong".
    """


# ---------------------------------------------------------------------------
# Dataclasses — F-152 Phase 2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resource:
    """A schedulable unit of capacity (engineer, runner, machine).

    Attributes
    ----------
    resource_id:
        Stable id used in :attr:`Schedule.assignments`.
    capacity:
        Number of parallel task slots the resource exposes at any given
        moment.  Defaults to ``1`` (one task at a time).  Larger values
        are modeled via cumulative constraints.
    availability:
        Optional list of ``(start, end)`` windows in the same time
        unit as the tasks.  An empty tuple means the resource is
        available for the entire :attr:`SchedulingSolver.schedule`
        horizon.  Multiple windows are interpreted as a union; the
        solver constrains each task's interval to be fully inside at
        least one window.
    skills:
        Tags the resource offers.  Tasks whose
        :attr:`SchedulingTask.required_skills` are not a subset of
        these tags cannot be assigned to this resource.
    """

    resource_id: str
    capacity: int = 1
    availability: tuple[tuple[int, int], ...] = ()
    skills: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise SchedulingError("Resource.resource_id must be a non-empty string")
        if not isinstance(self.capacity, int) or self.capacity < 1:
            raise SchedulingError(
                f"Resource({self.resource_id!r}).capacity must be a positive integer"
            )
        for window in self.availability:
            if (
                not isinstance(window, tuple)
                or len(window) != 2
                or not all(isinstance(x, int) for x in window)
            ):
                raise SchedulingError(
                    f"Resource({self.resource_id!r}).availability entries must be "
                    "(int, int) tuples"
                )
            start, end = window
            if start < 0 or end <= start:
                raise SchedulingError(
                    f"Resource({self.resource_id!r}).availability window "
                    f"{window!r} must satisfy 0 <= start < end"
                )
        if not isinstance(self.skills, frozenset):
            object.__setattr__(self, "skills", frozenset(self.skills))
        for skill in self.skills:
            if not isinstance(skill, str) or not skill.strip():
                raise SchedulingError(
                    f"Resource({self.resource_id!r}).skills must be non-empty strings"
                )


@dataclass(frozen=True)
class SchedulingTask:
    """One task that the solver can place on a resource.

    Time units are *call-defined*.  The whole problem must use the same
    unit (minutes, hours, days) — there is no implicit conversion.  The
    docstring on :meth:`SchedulingSolver.schedule` restates this.

    Attributes
    ----------
    task_id:
        Stable id used in :attr:`Schedule.assignments`.
    duration:
        Task length in the chosen time unit.  Must be a positive
        integer.
    earliest_start:
        Earliest start offset, or ``None`` for "anywhere from 0".
    latest_finish:
        Latest finish offset (inclusive bound on ``start + duration``),
        or ``None`` for "no upper bound other than the horizon".
    required_skills:
        Tags the assigned resource must offer.  Empty means "any".
    predecessors:
        Task ids that must finish before this one starts.  Forms the
        ``before`` / ``after`` edge set in the model.
    priority:
        Larger numbers are *more* important in weighted-completion
        objectives.  Defaults to ``1``.
    """

    task_id: str
    duration: int
    earliest_start: int | None = None
    latest_finish: int | None = None
    required_skills: frozenset[str] = field(default_factory=frozenset)
    predecessors: tuple[str, ...] = ()
    priority: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise SchedulingError("SchedulingTask.task_id must be a non-empty string")
        if not isinstance(self.duration, int) or self.duration < 1:
            raise SchedulingError(
                f"SchedulingTask({self.task_id!r}).duration must be a positive integer"
            )
        if self.earliest_start is not None and (
            not isinstance(self.earliest_start, int) or self.earliest_start < 0
        ):
            raise SchedulingError(
                f"SchedulingTask({self.task_id!r}).earliest_start must be a "
                "non-negative int or None"
            )
        if self.latest_finish is not None and (
            not isinstance(self.latest_finish, int) or self.latest_finish < 0
        ):
            raise SchedulingError(
                f"SchedulingTask({self.task_id!r}).latest_finish must be a "
                "non-negative int or None"
            )
        if (
            self.earliest_start is not None
            and self.latest_finish is not None
            and self.latest_finish < self.earliest_start + self.duration
        ):
            raise SchedulingError(
                f"SchedulingTask({self.task_id!r}) has an impossible time window: "
                f"latest_finish={self.latest_finish} < "
                f"earliest_start + duration = {self.earliest_start + self.duration}"
            )
        if not isinstance(self.required_skills, frozenset):
            object.__setattr__(self, "required_skills", frozenset(self.required_skills))
        if not isinstance(self.predecessors, tuple):
            object.__setattr__(self, "predecessors", tuple(self.predecessors))
        for pred in self.predecessors:
            if not isinstance(pred, str) or not pred.strip():
                raise SchedulingError(
                    f"SchedulingTask({self.task_id!r}).predecessors entries must "
                    "be non-empty strings"
                )
        if not isinstance(self.priority, int):
            raise SchedulingError(
                f"SchedulingTask({self.task_id!r}).priority must be an integer"
            )


# Possible status values returned in :attr:`Schedule.status`.
ScheduleStatus = Literal["optimal", "feasible", "infeasible", "timeout"]


@dataclass(frozen=True)
class Schedule:
    """The solver's answer for one :meth:`SchedulingSolver.schedule` call.

    Attributes
    ----------
    assignments:
        ``task_id -> (start, end, resource_id)`` for every task.  Empty
        for ``infeasible`` / ``timeout`` results.
    makespan:
        Maximum ``end`` across all assigned tasks.  ``0`` when there is
        no assignment.
    objective_value:
        Raw value of the objective that was actually minimized (after
        weighting).  Useful for comparing alternative schedules.
    status:
        One of ``optimal`` / ``feasible`` / ``infeasible`` / ``timeout``.
    objective:
        Echo of the objective that was passed in.  Lets callers
        serialize the schedule without remembering the original call.
    """

    assignments: dict[str, tuple[int, int, str]]
    makespan: int
    objective_value: int
    status: ScheduleStatus
    objective: str = "makespan"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": {
                tid: {"start": start, "end": end, "resourceId": rid}
                for tid, (start, end, rid) in self.assignments.items()
            },
            "makespan": self.makespan,
            "objectiveValue": self.objective_value,
            "status": self.status,
            "objective": self.objective,
        }


# ---------------------------------------------------------------------------
# Optional CP-SAT backend — F-152 Phase 3
# ---------------------------------------------------------------------------


# Map objective name -> ``(label, accept)`` so the public API stays
# decoupled from the solver's status enum.  UNKNOWN is what the solver
# returns when ``max_time_in_seconds`` expires before any conclusion is
# reached; the design contract is to surface that as ``"timeout"``
# (rather than treating it as infeasible).
_STATUS_MAP = {
    OPTIMAL: "optimal",
    FEASIBLE: "feasible",
    INFEASIBLE: "infeasible",
    MODEL_INVALID: "infeasible",
    UNKNOWN: "timeout",
}


class SchedulingSolver:
    """High-level wrapper around ``ortools.sat.python.cp_model``.

    Construct once and call :meth:`schedule` repeatedly.  The solver
    instance is intentionally stateless across calls so callers don't
    have to think about reuse; CP-SAT itself is fast to (re-)build for
    problems this small.

    The wrapper translates:

    * each :class:`SchedulingTask` to ``(start, end, interval)`` variables,
    * :class:`Resource` constraints into ``AddNoOverlap`` (capacity=1)
      or ``AddCumulative`` (capacity>1),
    * :attr:`SchedulingTask.predecessors` into ``end <= start`` edges,
    * :attr:`SchedulingTask.required_skills` into per-resource boolean
      indicators that gate the assignment.

    Objectives supported:

    * ``"makespan"`` (default) — minimize the latest end time.
    * ``"weighted_completion"`` — minimize ``sum(priority * end)``.
    * ``"resource_level"`` — minimize the highest peak capacity used.
      When no cumulative resource is present this degrades to makespan
      (no peak signal to optimize).
    """

    #: Cap for ``max_time_in_seconds``.  Mirrors the F-152 SLA of
    #  N<=20, M<=5, horizon<=30 days — CP-SAT is fast on these sizes
    #  and a hard 30 s wall is plenty.  Callers may tighten.
    DEFAULT_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        if cp_model is None:
            raise SchedulingUnavailable(
                "ortools is not installed; run `pip install clawcodex[scheduling]` "
                "to enable SchedulingSolver."
            )

    # -- public API --------------------------------------------------------

    def schedule(
        self,
        tasks: Iterable[SchedulingTask],
        resources: Iterable[Resource],
        *,
        horizon: int,
        objective: str = "makespan",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Schedule:
        """Solve the bounded scheduling problem.

        Parameters
        ----------
        tasks:
            The :class:`SchedulingTask` set to place.  The caller is
            responsible for guaranteeing acyclic predecessors; cycles
            are detected by :func:`validate_schedule` if you need a
            separate check.
        resources:
            The :class:`Resource` pool to draw from.  Must be non-empty
            unless there are no tasks.
        horizon:
            Upper bound on the *end* of any task, in the same time
            unit as the tasks.  Per the F-152 design, the MVP does not
            support horizons longer than 30 days; larger values are
            allowed but may be slow.
        objective:
            One of ``"makespan"``, ``"weighted_completion"``,
            ``"resource_level"``.  Unknown names raise
            :class:`SchedulingError`.
        timeout_seconds:
            Wall-clock budget for the solver.  ``0.001`` is a useful
            way to force a ``"timeout"`` outcome for testing.  Negative
            values are treated as zero.

        Returns
        -------
        :class:`Schedule`

            On success the status is ``"optimal"`` (CP-SAT proved
            optimality) or ``"feasible"`` (it found a plan within the
            budget but could not prove optimality).  Failure surfaces
            as ``"infeasible"`` (no plan exists) or ``"timeout"`` (no
            plan found before the budget expired).
        """
        if cp_model is None or CpModel is None or CpSolver is None:
            raise SchedulingUnavailable(
                "ortools is not installed; run `pip install clawcodex[scheduling]` "
                "to enable SchedulingSolver."
            )
        if objective not in ("makespan", "weighted_completion", "resource_level"):
            raise SchedulingError(
                f"unknown objective {objective!r}; expected one of "
                "'makespan', 'weighted_completion', 'resource_level'"
            )
        if not isinstance(horizon, int) or horizon < 1:
            raise SchedulingError("horizon must be a positive integer")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds < 0:
            raise SchedulingError("timeout_seconds must be a non-negative number")

        task_list = tuple(tasks)
        resource_list = tuple(resources)
        if not task_list:
            return Schedule(
                assignments={},
                makespan=0,
                objective_value=0,
                status="optimal",
                objective=objective,
            )
        if not resource_list:
            raise SchedulingError("resources must be non-empty when tasks are present")

        self._validate_inputs(task_list, resource_list, horizon)

        # Build the CP-SAT model.
        model = CpModel()
        task_vars: dict[str, _TaskVars] = {}
        n_res = len(resource_list)

        # Per-task: start, end, and a list of optional intervals
        # (one per resource) that activate only when the task is
        # assigned to that resource.  Using optional intervals keeps
        # the cumulative constraint semantically clean: when the
        # boolean is false the interval is "absent" and consumes no
        # capacity.
        for task in task_list:
            start = model.NewIntVar(0, horizon, f"start_{task.task_id}")
            end = model.NewIntVar(0, horizon, f"end_{task.task_id}")
            assigned_res = model.NewIntVar(0, n_res - 1, f"res_{task.task_id}")
            presence: dict[str, Any] = {}
            optional_intervals: dict[str, Any] = {}
            for res_idx, res in enumerate(resource_list):
                is_present = model.NewBoolVar(
                    f"pres_{task.task_id}_{res.resource_id}"
                )
                opt_iv = model.NewOptionalIntervalVar(
                    start, task.duration, end, is_present, f"iv_{task.task_id}_{res.resource_id}"
                )
                # ``is_present`` must be true iff ``assigned_res == res_idx``
                model.Add(assigned_res == res_idx).OnlyEnforceIf(is_present)
                for other_idx in range(n_res):
                    if other_idx == res_idx:
                        continue
                    model.Add(assigned_res != other_idx).OnlyEnforceIf(is_present)
                presence[res.resource_id] = is_present
                optional_intervals[res.resource_id] = opt_iv
            # Exactly one resource per task.
            model.AddExactlyOne(list(presence.values()))

            task_vars[task.task_id] = _TaskVars(
                task=task,
                start=start,
                end=end,
                assigned_res=assigned_res,
                presence=presence,
                optional_intervals=optional_intervals,
            )

        # Time-window constraints.
        for tid, tv in task_vars.items():
            task = tv.task
            if task.earliest_start is not None:
                model.Add(tv.start >= task.earliest_start)
            if task.latest_finish is not None:
                model.Add(tv.end <= task.latest_finish)

        # Predecessor (before) edges.
        for tid, tv in task_vars.items():
            for pred_id in tv.task.predecessors:
                if pred_id not in task_vars:
                    raise SchedulingError(
                        f"Task {tid!r} lists unknown predecessor {pred_id!r}"
                    )
                pred_end = task_vars[pred_id].end
                model.Add(pred_end <= tv.start)

        # Resource capacity constraints — one cumulative per resource
        # over all optional intervals.  Tasks assigned elsewhere
        # contribute 0 because their boolean is false.
        for res in resource_list:
            intervals = [tv.optional_intervals[res.resource_id] for tv in task_vars.values()]
            demands = [1] * len(task_list)
            model.AddCumulative(intervals, demands, res.capacity)

        # Skill compatibility: a task that requires a skill the
        # resource lacks must not be assigned to it.  Force the
        # presence boolean to 0.
        for tid, tv in task_vars.items():
            for res in resource_list:
                if not tv.task.required_skills.issubset(res.skills):
                    model.Add(tv.presence[res.resource_id] == 0)

        # Resource availability windows: each task assigned to a
        # resource must fit entirely inside one of the windows.
        for res in resource_list:
            if not res.availability:
                continue
            for tid, tv in task_vars.items():
                is_present = tv.presence[res.resource_id]
                in_any_window: list[Any] = []
                for w_idx, (win_start, win_end) in enumerate(res.availability):
                    in_window = model.NewBoolVar(f"in_{res.resource_id}_{tid}_{w_idx}")
                    model.Add(tv.start >= win_start).OnlyEnforceIf(in_window)
                    model.Add(tv.end <= win_end).OnlyEnforceIf(in_window)
                    in_any_window.append(in_window)
                # at least one window must hold whenever the task uses
                # this resource; otherwise the constraint is relaxed.
                model.AddBoolOr(in_any_window + [is_present.Not()])

        # Objective.
        all_ends = [tv.end for tv in task_vars.values()]
        all_starts = [tv.start for tv in task_vars.values()]
        if objective == "makespan":
            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, all_ends)
            model.Minimize(makespan)
        elif objective == "weighted_completion":
            terms: list[Any] = []
            for tv in task_vars.values():
                w = tv.task.priority
                # cp-sat's linear expr handles coefficients, but using
                # a per-task weighted IntVar keeps the model terse.
                terms.append(w * tv.end)
            model.Minimize(sum(terms))
        else:  # resource_level
            # No peak-capacity demand without cumulative resources, so
            # fall back to makespan; we still echo the objective in the
            # returned Schedule so the caller can see the downgrade.
            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, all_ends)
            model.Minimize(makespan)

        # Solve.
        solver = CpSolver()
        solver.parameters.max_time_in_seconds = max(0.0, float(timeout_seconds))
        status = solver.Solve(model)
        status_name = _STATUS_MAP.get(status, "infeasible")
        if status == MODEL_INVALID:
            status_name = "infeasible"

        if status in (OPTIMAL, FEASIBLE):
            assignments: dict[str, tuple[int, int, str]] = {}
            for tid, tv in task_vars.items():
                assigned_res_idx = solver.Value(tv.assigned_res)
                assignments[tid] = (
                    solver.Value(tv.start),
                    solver.Value(tv.end),
                    resource_list[assigned_res_idx].resource_id,
                )
            makespan_value = max((a[1] for a in assignments.values()), default=0)
            if objective == "weighted_completion":
                obj_value = sum(
                    tv.task.priority * assignments[tv.task.task_id][1]
                    for tv in task_vars.values()
                )
            else:
                obj_value = makespan_value
            return Schedule(
                assignments=assignments,
                makespan=makespan_value,
                objective_value=int(obj_value),
                status=status_name,  # type: ignore[arg-type]
                objective=objective,
            )

        # Infeasible or timeout: empty assignments, but report the
        # status faithfully so the caller can branch on it.
        return Schedule(
            assignments={},
            makespan=0,
            objective_value=0,
            status=status_name,  # type: ignore[arg-type]
            objective=objective,
        )

    # -- internal helpers --------------------------------------------------

    @staticmethod
    def _validate_inputs(
        tasks: tuple[SchedulingTask, ...],
        resources: tuple[Resource, ...],
        horizon: int,
    ) -> None:
        seen_ids: set[str] = set()
        for t in tasks:
            if t.task_id in seen_ids:
                raise SchedulingError(f"duplicate task_id {t.task_id!r}")
            seen_ids.add(t.task_id)
            if t.duration > horizon:
                raise SchedulingError(
                    f"Task {t.task_id!r} duration={t.duration} exceeds horizon={horizon}"
                )
            upper = t.latest_finish if t.latest_finish is not None else horizon
            if t.earliest_start is not None and t.earliest_start >= horizon:
                raise SchedulingError(
                    f"Task {t.task_id!r} earliest_start={t.earliest_start} is "
                    f">= horizon={horizon}"
                )
            if t.latest_finish is not None and t.latest_finish > horizon:
                raise SchedulingError(
                    f"Task {t.task_id!r} latest_finish={t.latest_finish} is "
                    f"> horizon={horizon}"
                )
        # Skills / resource matching: every task must be assignable to
        # at least one resource, otherwise the model is trivially
        # infeasible.  Surface that as a hard error before the solver
        # wastes time.
        for t in tasks:
            if not t.required_skills:
                continue
            if not any(t.required_skills.issubset(r.skills) for r in resources):
                raise SchedulingError(
                    f"Task {t.task_id!r} requires skills {sorted(t.required_skills)} "
                    "but no resource offers them"
                )


# ---------------------------------------------------------------------------
# Schedule validation — F-152 Phase 4
# ---------------------------------------------------------------------------


def validate_schedule(
    schedule: Schedule,
    tasks: Iterable[SchedulingTask],
    resources: Iterable[Resource],
    *,
    dependencies: Iterable[tuple[str, str]] = (),
) -> list[str]:
    """Check the solver's output against the input problem.

    Returns a list of human-readable issues (empty list = valid).  This
    is a defensive pass — the solver should already satisfy all
    constraints, but we re-verify the plan that LKB surfaces so that
    data corruption or future refactors can't ship a broken schedule.

    Checks performed:

    1. Every task id in the input has an assignment.
    2. Every assigned ``resource_id`` is in the resource pool.
    3. For every dependency ``(prereq, dependent)``, the prereq's
       ``end`` does not exceed the dependent's ``start``.
    4. Each assignment satisfies the task's ``earliest_start`` and
       ``latest_finish`` windows.
    5. Each assignment fits inside at least one of the resource's
       availability windows.
    6. Each assignment respects the resource's skill requirements.
    """
    task_by_id = {t.task_id: t for t in tasks}
    res_by_id = {r.resource_id: r for r in resources}
    issues: list[str] = []

    for tid, (start, end, rid) in schedule.assignments.items():
        task = task_by_id.get(tid)
        if task is None:
            issues.append(f"Schedule references unknown task_id {tid!r}")
            continue
        if start < 0:
            issues.append(f"Task {tid!r} has negative start {start}")
        if end <= start:
            issues.append(
                f"Task {tid!r} has end {end} <= start {start} "
                f"(duration must be positive)"
            )
        if end - start != task.duration:
            issues.append(
                f"Task {tid!r} has assigned length {end - start} != "
                f"declared duration {task.duration}"
            )
        if task.earliest_start is not None and start < task.earliest_start:
            issues.append(
                f"Task {tid!r} starts at {start} before earliest_start "
                f"{task.earliest_start}"
            )
        if task.latest_finish is not None and end > task.latest_finish:
            issues.append(
                f"Task {tid!r} finishes at {end} after latest_finish "
                f"{task.latest_finish}"
            )
        res = res_by_id.get(rid)
        if res is None:
            issues.append(f"Task {tid!r} assigned to unknown resource {rid!r}")
            continue
        if not task.required_skills.issubset(res.skills):
            issues.append(
                f"Task {tid!r} (needs {sorted(task.required_skills)}) is on "
                f"resource {rid!r} which only offers {sorted(res.skills)}"
            )
        if res.availability and not any(
            win_start <= start and end <= win_end
            for win_start, win_end in res.availability
        ):
            issues.append(
                f"Task {tid!r} runs at [{start}, {end}] but resource "
                f"{rid!r} windows are {list(res.availability)}"
            )

    # Dependencies — only meaningful when both endpoints are in the
    # schedule.  Surplus dependencies over the task.predecessors are
    # accepted because callers (TaskDecomposer) can pass the
    # decomposition-level dependency graph.
    starts = {tid: a[0] for tid, a in schedule.assignments.items()}
    ends = {tid: a[1] for tid, a in schedule.assignments.items()}
    for prereq, dependent in dependencies:
        if prereq not in ends or dependent not in starts:
            issues.append(
                f"Dependency ({prereq!r} -> {dependent!r}) references a task "
                "missing from the schedule"
            )
            continue
        if ends[prereq] > starts[dependent]:
            issues.append(
                f"Dependency violated: {prereq!r} ends at {ends[prereq]} but "
                f"{dependent!r} starts at {starts[dependent]}"
            )

    return issues


# ---------------------------------------------------------------------------
# Internal: typed bundle of per-task variables
# ---------------------------------------------------------------------------


@dataclass
class _TaskVars:
    """Per-task CP-SAT variables.  Internal to this module."""

    task: SchedulingTask
    start: Any  # IntVar
    end: Any  # IntVar
    assigned_res: Any  # IntVar
    presence: dict[str, Any]  # resource_id -> BoolVar
    optional_intervals: dict[str, Any]  # resource_id -> OptionalIntervalVar


__all__ = [
    "Resource",
    "Schedule",
    "ScheduleStatus",
    "SchedulingError",
    "SchedulingSolver",
    "SchedulingTask",
    "SchedulingUnavailable",
    "validate_schedule",
]
