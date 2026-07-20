"""Deterministic seed planner and coordinator prompt for F-118."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Subtask, TaskPlan

if TYPE_CHECKING:
    from ..issue import Issue


_LIST_ITEM = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+?)\s*$")
_SEQUENTIAL_MARKERS = (" then ", "after ", "once ", "然后", "之后", "完成后", "再")
_DISCOVERY_MARKERS = (
    "analyze",
    "audit",
    "inspect",
    "investigate",
    "map ",
    "梳理",
    "分析",
    "调查",
    "定位",
)
_VERIFICATION_MARKERS = (
    "test",
    "verify",
    "validation",
    "regression",
    "测试",
    "验证",
    "回归",
    "检查",
)


class TaskDecomposer:
    """Create a bounded seed graph that the coordinator may refine at runtime."""

    def __init__(
        self,
        *,
        max_subtasks: int = 8,
        max_parallel: int = 3,
        max_waves: int = 6,
    ) -> None:
        self.max_subtasks = max(1, int(max_subtasks))
        self.max_parallel = max(1, int(max_parallel))
        self.max_waves = max(1, int(max_waves))

    def decompose_issue(self, issue: "Issue") -> TaskPlan:
        title = str(issue.title or issue.identifier or issue.id or "Complex task").strip()
        description = str(issue.description or "").strip()
        explicit = self._extract_explicit_tasks(description)
        if len(explicit) >= 2:
            subtasks = self._from_explicit_tasks(explicit)
        else:
            subtasks = self._bounded_fallback_tasks(title, description)
        subtasks = tuple(subtasks[: self.max_subtasks])
        waves = _build_waves(subtasks, max_parallel=self.max_parallel)
        if len(waves) > self.max_waves:
            # A long sequential list can legitimately need more waves than
            # the configured budget. Fall back to a compact phased plan
            # instead of crashing the entire swarm dispatch.
            subtasks = tuple(self._bounded_fallback_tasks(title, description))
            waves = _build_waves(subtasks, max_parallel=self.max_parallel)
        plan = TaskPlan(
            goal=title,
            subtasks=subtasks,
            waves=waves,
            max_parallel=self.max_parallel,
        )
        plan.validate(max_subtasks=self.max_subtasks, max_waves=self.max_waves)
        return plan

    def _extract_explicit_tasks(self, description: str) -> list[str]:
        tasks: list[str] = []
        for line in description.splitlines():
            match = _LIST_ITEM.match(line)
            if match:
                text = match.group(1).strip()
                if text and len(text) >= 4:
                    tasks.append(text[:600])
            if len(tasks) >= self.max_subtasks:
                break
        return tasks

    def _from_explicit_tasks(self, rows: list[str]) -> list[Subtask]:
        tasks: list[Subtask] = []
        discovery_ids: list[str] = []
        for index, row in enumerate(rows[: self.max_subtasks], start=1):
            normalized = f" {row.lower()} "
            task_id = f"task-{index}"
            is_discovery = any(marker in normalized for marker in _DISCOVERY_MARKERS)
            is_verification = any(marker in normalized for marker in _VERIFICATION_MARKERS)
            dependencies: list[str] = []
            if is_verification:
                # Tests and final verification must observe completed code.
                dependencies.extend(task.id for task in tasks)
            elif not is_discovery:
                # Independent implementation tasks may run together after the
                # shared discovery phase has established the change surface.
                dependencies.extend(discovery_ids)
            if index > 1 and any(marker in normalized for marker in _SEQUENTIAL_MARKERS):
                dependencies.append(f"task-{index - 1}")
            depends_on = tuple(dict.fromkeys(dependencies))
            tasks.append(
                Subtask(
                    id=task_id,
                    title=row[:120],
                    description=row,
                    depends_on=depends_on,
                    verification="Report concrete evidence and changed files.",
                )
            )
            if is_discovery:
                discovery_ids.append(task_id)
        return tasks

    @staticmethod
    def _fallback_tasks(title: str, description: str) -> list[Subtask]:
        context = description[:1200] or title
        return [
            Subtask(
                id="task-1",
                title="Investigate and bound the change",
                description=f"Inspect the repository and identify the exact implementation surface for: {context}",
                verification="Return verified facts, affected files, and risks.",
            ),
            Subtask(
                id="task-2",
                title="Implement the change",
                description=f"Implement the smallest complete solution for: {title}",
                depends_on=("task-1",),
                verification="Return changed files and explain how the root cause is addressed.",
            ),
            Subtask(
                id="task-3",
                title="Verify and challenge the result",
                description="Run focused tests, then check for regressions and incomplete edge cases.",
                depends_on=("task-2",),
                verification="Return commands, exit codes, failures, and residual risks.",
            ),
        ]

    def _bounded_fallback_tasks(self, title: str, description: str) -> list[Subtask]:
        limit = min(self.max_subtasks, self.max_waves, 3)
        if limit >= 3:
            return self._fallback_tasks(title, description)
        context = description[:1200] or title
        if limit == 1:
            return [
                Subtask(
                    id="task-1",
                    title="Investigate, implement, and verify",
                    description=f"Complete the bounded change end to end: {context}",
                    verification="Report changed files, tests, exit codes, and residual risks.",
                )
            ]
        return [
            Subtask(
                id="task-1",
                title="Investigate and bound the change",
                description=f"Identify the exact implementation surface for: {context}",
                verification="Return verified facts, affected files, and risks.",
            ),
            Subtask(
                id="task-2",
                title="Implement and verify the change",
                description=f"Implement the solution and run focused regression checks for: {title}",
                depends_on=("task-1",),
                verification="Report changed files, tests, exit codes, and residual risks.",
            ),
        ]


def _build_waves(
    subtasks: tuple[Subtask, ...],
    *,
    max_parallel: int,
) -> tuple[tuple[str, ...], ...]:
    remaining = {task.id: set(task.depends_on) for task in subtasks}
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while remaining:
        ready = sorted(task_id for task_id, deps in remaining.items() if deps <= completed)
        if not ready:
            raise ValueError("task plan contains a dependency cycle")
        for start in range(0, len(ready), max_parallel):
            wave = tuple(ready[start : start + max_parallel])
            waves.append(wave)
            completed.update(wave)
            for task_id in wave:
                remaining.pop(task_id, None)
    return tuple(waves)


def write_task_plan(plan: TaskPlan, workspace: Path) -> Path:
    target = Path(workspace) / ".orchestrator_control" / "task_decomposition.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def validate_task_execution(plan_path: Path, seed_plan: TaskPlan) -> None:
    """Validate coordinator-reported execution evidence against the seed graph."""
    try:
        payload = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"task execution plan is unreadable: {exc}") from exc
    rows = payload.get("subtasks") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("task execution plan must contain a subtasks list")
    expected_ids = {task.id for task in seed_plan.subtasks}
    if any(not isinstance(row, dict) or row.get("id") is None for row in rows):
        raise ValueError("each task execution evidence row must have an id")
    by_id = {str(row["id"]): row for row in rows}
    if len(rows) != len(by_id) or set(by_id) != expected_ids:
        raise ValueError("task execution evidence must cover exactly the seed task ids")

    intervals: dict[str, tuple[float, float]] = {}
    for task in seed_plan.subtasks:
        row = _load_task_execution_row(Path(plan_path), task.id, by_id[task.id])
        if str(row.get("status", "")).strip().lower() != "completed":
            raise ValueError(f"subtask {task.id} is not marked completed")
        evidence = row.get("evidence")
        if not _has_completion_evidence(evidence):
            raise ValueError(f"subtask {task.id} has no completion evidence")
        started_at = _parse_execution_time(row.get("started_at"), task.id, "started_at")
        completed_at = _parse_execution_time(row.get("completed_at"), task.id, "completed_at")
        if completed_at < started_at:
            raise ValueError(f"subtask {task.id} completed before it started")
        intervals[task.id] = (started_at, completed_at)

    for task in seed_plan.subtasks:
        started_at, _ = intervals[task.id]
        for dependency in task.depends_on:
            if intervals[dependency][1] > started_at:
                raise ValueError(
                    f"subtask {task.id} started before dependency {dependency} completed"
                )

    events: list[tuple[float, int]] = []
    for started_at, completed_at in intervals.values():
        events.append((started_at, 1))
        events.append((completed_at, -1))
    active = 0
    peak = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        active += delta
        peak = max(peak, active)
    if peak > seed_plan.max_parallel:
        raise ValueError(
            f"task execution peak parallelism {peak} exceeds limit {seed_plan.max_parallel}"
        )


def _load_task_execution_row(
    plan_path: Path,
    task_id: str,
    inline_row: dict[str, object],
) -> dict[str, object]:
    """Overlay a worker's per-task evidence file onto the seed-plan row."""
    evidence_path = plan_path.parent / "task_evidence" / f"{task_id}.json"
    if not evidence_path.exists():
        return inline_row
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"subtask {task_id} evidence file is unreadable: {exc}") from exc
    if not isinstance(payload, dict) or str(payload.get("id", "")) != task_id:
        raise ValueError(f"subtask {task_id} evidence file has the wrong id")
    merged = dict(inline_row)
    for field in ("status", "evidence", "started_at", "completed_at"):
        if field in payload:
            merged[field] = payload[field]
    # Worker-authored timestamps are claims, not trustworthy execution
    # facts. The atomic evidence file's mtime is recorded by the host and
    # gives deterministic dependency ordering without letting a model invent
    # a future timestamp. Inline legacy evidence keeps its original semantics.
    recorded_at = evidence_path.stat().st_mtime
    merged["started_at"] = recorded_at
    merged["completed_at"] = recorded_at
    return merged


def _has_completion_evidence(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(_has_completion_evidence(item) for item in value)
    if isinstance(value, dict):
        return any(_has_completion_evidence(item) for item in value.values())
    return False


def _parse_execution_time(value: object, task_id: str, field: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str):
            result = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"subtask {task_id} has invalid {field}") from exc
    if not math.isfinite(result):
        raise ValueError(f"subtask {task_id} has invalid {field}")
    return result


def build_swarm_prompt(issue: "Issue", plan: TaskPlan, plan_path: Path) -> str:
    plan_json = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    description = str(issue.description or "").strip()
    evidence_dir = plan_path.parent / "task_evidence"
    return f"""You are the coordinator for a dynamically decomposed task.

Issue: {issue.title or issue.identifier or issue.id}
Description:
{description}

The seed plan below is stored at {plan_path}. Review it before acting. You may refine task descriptions or dependencies, but stay within {len(plan.subtasks)} subtasks, {len(plan.waves)} waves, and at most {plan.max_parallel} active workers.

{plan_json}

Execution rules:
1. Work wave by wave. Spawn workers only for tasks whose dependencies are complete.
2. Give each worker one bounded task and require: verified facts, changed files, commands/tests, and residual risks.
3. Do not let two workers edit the same file concurrently. Serialize overlapping work.
4. You do not have write tools, so evidence recording must be delegated. For every planned task, use a write-capable worker (not an Explore-only worker) and include the exact task id plus these instructions in its Agent prompt:
   - Record only this task in {evidence_dir}/<task-id>.json. Never edit task_decomposition.json. Unique per-task files avoid write conflicts between parallel workers.
   - Before substantive work, atomically write id, status="in_progress", and started_at. Use the current output of `date +%s`; never invent or estimate timestamps.
   - After successful work, atomically replace it with id, status="completed", non-empty evidence, started_at, and completed_at from a fresh `date +%s`. Evidence must name changed files and exact verification commands/results. Do not mark a failed command as completed. The validator uses the evidence file's host mtime for dependency ordering.
   - Do not commit files under .orchestrator_control.
5. Run the repository's focused verification after implementation. If verification fails, create a bounded repair task instead of declaring success.
6. Finish with a structured summary: completed tasks, changes, verification evidence, unresolved risks.
"""


__all__ = [
    "TaskDecomposer",
    "build_swarm_prompt",
    "validate_task_execution",
    "write_task_plan",
]
