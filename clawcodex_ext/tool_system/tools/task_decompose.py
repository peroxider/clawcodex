"""TaskDecompose tool for Logical Kanban (F-149).

Exposes the :class:`TaskDecomposer` service to the agent loop. The tool is
read-only with respect to task state: it returns a validated plan, but the
agent must still call TaskCreate / TaskUpdate to commit tasks.
"""

from __future__ import annotations

from typing import Any

from ..build_tool import Tool, build_tool
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from clawcodex_ext.logical_kanban import TaskDecomposer
from clawcodex_ext.logical_kanban.audit import get_audit_log
from clawcodex_ext.logical_kanban.flags import is_logical_kanban_enabled
from src.utils.task_flags import is_todo_v2_enabled


def _task_decompose_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    goal = tool_input.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ToolInputError("goal must be a non-empty string")

    ctx = tool_input.get("context", "")
    if not isinstance(ctx, str):
        raise ToolInputError("context must be a string when provided")

    acceptance_criteria = _string_list(tool_input.get("acceptance_criteria"))

    max_steps = tool_input.get("max_steps", 8)
    if not isinstance(max_steps, int) or isinstance(max_steps, bool):
        raise ToolInputError("max_steps must be an integer")
    if max_steps < 1 or max_steps > 20:
        raise ToolInputError("max_steps must be between 1 and 20")

    scheduling_constraints = tool_input.get("scheduling_constraints")
    if scheduling_constraints is not None and not isinstance(scheduling_constraints, dict):
        raise ToolInputError("scheduling_constraints must be a dict or None")

    provider = getattr(context, "_active_provider", None)
    if provider is None:
        return ToolResult(
            name="TaskDecompose",
            output={
                "error": "No active LLM provider is available for decomposition.",
                "decompositionRunId": None,
                "goal": goal,
                "tasks": [],
                "dependencies": [],
                "assumptions": [],
                "ambiguities": [],
                "validation": {"validationRunId": None, "result": "error", "issues": []},
            },
            is_error=True,
        )

    existing_tasks = tuple(context.tasks.values())
    decomposer = TaskDecomposer(llm_provider=provider)
    plan = decomposer.decompose(
        goal=goal,
        context=ctx,
        acceptance_criteria=tuple(acceptance_criteria),
        max_steps=max_steps,
        existing_tasks=existing_tasks,
        scheduling_constraints=scheduling_constraints,
    )

    # Re-emit the audit event through the session-local audit log so it is
    # persisted alongside other LKB events for this context.  We delegate
    # the actual emission to ``decomposer._emit_audit_event`` so the F-151
    # ``lkb_method_referenced`` events (one per referenced method) ride
    # along on the same log.
    session_audit_log = get_audit_log(context)
    decomposer._emit_audit_event(plan, audit_log=session_audit_log)

    # Resolve the validation result to include in the wire response.
    validation = _build_validation(plan)

    output: dict[str, Any] = {
        "decompositionRunId": plan.decomposition_run_id,
        "goal": plan.goal,
        "tasks": [t.to_dict() for t in plan.tasks],
        "dependencies": [list(d) for d in plan.dependencies],
        "assumptions": list(plan.assumptions),
        "ambiguities": (
            [a.to_dict() for a in plan.ambiguity_report.detected_ambiguities]
            if plan.ambiguity_report is not None
            else []
        ),
        "validation": validation,
        "schedule": plan.schedule.to_dict() if plan.schedule is not None else None,
        "schedulingConstraints": (
            dict(plan.scheduling_constraints) if plan.scheduling_constraints is not None else None
        ),
    }
    return ToolResult(name="TaskDecompose", output=output)


def _build_validation(plan: "Any") -> dict[str, Any]:
    validation_run = getattr(plan, "validation_run", None)
    if validation_run is not None:
        return {
            "validationRunId": validation_run.validation_run_id,
            "result": validation_run.result,
            "issues": [issue.to_dict() for issue in validation_run.issues],
        }

    # Fallback when no validation run is present.
    validation_run_id = getattr(plan, "validation_run_id", None)
    ambiguity_report = getattr(plan, "ambiguity_report", None)
    if ambiguity_report is not None and ambiguity_report.needs_clarification:
        return {
            "validationRunId": validation_run_id,
            "result": "fail",
            "issues": [
                {
                    "code": "decomposition_ambiguous",
                    "message": "Generated plan contains ambiguous acceptance criteria or descriptions.",
                    "rule": "LKB-FUZZY-001",
                    "severity": "error",
                }
            ],
        }
    return {
        "validationRunId": validation_run_id,
        "result": "pass",
        "issues": [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def _enabled() -> bool:
    return is_todo_v2_enabled() and is_logical_kanban_enabled()


TaskDecomposeTool: Tool = build_tool(
    name="TaskDecompose",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "minLength": 1},
            "context": {"type": "string"},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 20},
            "scheduling_constraints": {"type": "object"},
        },
        "required": ["goal"],
    },
    call=_task_decompose_call,
    prompt="""\
Use this tool to break a complex, multi-step goal into a structured, validated task plan.

## When to Use This Tool

- The goal clearly requires 3 or more sequential or parallel steps.
- You want the Logical Kanban system to check the proposed plan for cyclic dependencies,
  impossible dependencies, and ambiguous acceptance criteria before you commit tasks.
- You are starting a non-trivial implementation and want a reusable plan to guide
  TaskCreate / TaskUpdate calls.

## When NOT to Use This Tool

- For trivial or single-step goals — just create the task directly with TaskCreate.
- When you already have a clear, validated task list in place.

## Output

Returns a validated decomposition plan:
- **decompositionRunId**: Stable id for this decomposition run.
- **tasks**: Proposed tasks with subjects (imperative form), descriptions, active forms,
  acceptance criteria, blockedBy, and LKB metadata.
- **dependencies**: Pairs of (prerequisite_id, dependent_id) describing the dependency graph.
- **assumptions**: Explicit assumptions the plan relies on.
- **ambiguities**: Detected ambiguities in the generated plan, if any.
- **validation**: A validation object with `result` (pass|fail) and `issues`.
- **schedule**: Optional F-152 schedule produced by OR-Tools CP-SAT.  Populated only
  when ``scheduling_constraints`` is supplied.  See F-152 for the constraints shape.
- **schedulingConstraints**: Echo of the input constraints (or ``null``).

## Important

This tool is read-only: it does **not** create or modify tasks. After reviewing the plan,
call TaskCreate / TaskUpdate yourself to commit the tasks you want to keep.
""",
    description="Decompose a high-level goal into a validated task plan.",
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    is_enabled=_enabled,
)
