"""Model-callable tools for upstream-compatible thread goals."""

from __future__ import annotations

from typing import Any, Iterable

from clawcodex_ext.tool_system.build_tool import Tool, build_tool
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.protocol import ToolResult

from .gate import goal_enabled
from .model import ThreadGoal, ThreadGoalStatus
from .protocol import ThreadGoalDTO
from .service import GoalService, GoalServiceError

GET_GOAL_TOOL_NAME = "get_goal"
CREATE_GOAL_TOOL_NAME = "create_goal"
UPDATE_GOAL_TOOL_NAME = "update_goal"

GOAL_MODEL_TOOL_NAMES = frozenset(
    {GET_GOAL_TOOL_NAME, CREATE_GOAL_TOOL_NAME, UPDATE_GOAL_TOOL_NAME}
)

GET_GOAL_DESCRIPTION = (
    "Get the current goal for this thread, including status, budgets, "
    "token and elapsed-time usage, and remaining token budget."
)

CREATE_GOAL_DESCRIPTION = (
    "Create a goal only when explicitly requested by the user or "
    "system/developer instructions; do not infer goals from ordinary tasks.\n"
    "Set token_budget only when an explicit token budget is requested. "
    f"Fails if an unfinished goal exists; use {UPDATE_GOAL_TOOL_NAME} only for status."
)

UPDATE_GOAL_DESCRIPTION = """Update the existing goal.
Use this tool only to mark the goal achieved or genuinely blocked.
Set status to `complete` only when the objective has actually been achieved and no required work remains.
Set status to `blocked` only when the same blocking condition has repeated for at least three consecutive goal turns, counting the original/user-triggered turn and any automatic continuations, and the agent cannot make meaningful progress without user input or an external-state change.
If the user resumes a goal that was previously marked `blocked`, treat the resumed run as a fresh blocked audit. If the same blocking condition then repeats for at least three consecutive resumed goal turns, set status to `blocked` again.
Once the blocked threshold is satisfied, do not keep reporting that you are still blocked while leaving the goal active; set status to `blocked`.
Do not use `blocked` merely because the work is hard, slow, uncertain, incomplete, or would benefit from clarification.
Do not mark a goal complete merely because its budget is nearly exhausted or because you are stopping work.
You cannot use this tool to pause, resume, budget-limit, or usage-limit a goal; those status changes are controlled by the user or system.
When marking a budgeted goal achieved with status `complete`, report the final token usage from the tool result to the user."""

_OBJECTIVE_DESCRIPTION = (
    "Required. The concrete objective to start pursuing. This starts a new "
    "active goal when no goal exists or replaces the current goal when it is complete."
)

_TOKEN_BUDGET_DESCRIPTION = (
    "Positive token budget for the new goal. Omit unless explicitly requested."
)

_UPDATE_STATUS_DESCRIPTION = (
    "Required. Set to `complete` only when the objective is achieved and no "
    "required work remains. Set to `blocked` only after the same blocking "
    "condition has recurred for at least three consecutive goal turns and the "
    "agent is at an impasse. After a previously blocked goal is resumed, the "
    "resumed run starts a fresh blocked audit."
)


def make_goal_model_tools() -> list[Tool]:
    """Build the three model-visible goal tools."""
    return [
        build_tool(
            name=GET_GOAL_TOOL_NAME,
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            call=_get_goal,
            prompt=GET_GOAL_DESCRIPTION,
            description=GET_GOAL_DESCRIPTION,
            is_enabled=goal_enabled,
            is_concurrency_safe=lambda _input: True,
            is_read_only=lambda _input: True,
            user_facing_name=lambda _input: GET_GOAL_TOOL_NAME,
        ),
        build_tool(
            name=CREATE_GOAL_TOOL_NAME,
            input_schema={
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": _OBJECTIVE_DESCRIPTION,
                    },
                    "token_budget": {
                        "type": "integer",
                        "description": _TOKEN_BUDGET_DESCRIPTION,
                    },
                },
                "required": ["objective"],
                "additionalProperties": False,
            },
            call=_create_goal,
            prompt=CREATE_GOAL_DESCRIPTION,
            description=CREATE_GOAL_DESCRIPTION,
            is_enabled=goal_enabled,
            user_facing_name=lambda _input: CREATE_GOAL_TOOL_NAME,
        ),
        build_tool(
            name=UPDATE_GOAL_TOOL_NAME,
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["complete", "blocked"],
                        "description": _UPDATE_STATUS_DESCRIPTION,
                    }
                },
                "required": ["status"],
                "additionalProperties": False,
            },
            call=_update_goal,
            prompt=UPDATE_GOAL_DESCRIPTION,
            description=UPDATE_GOAL_DESCRIPTION,
            is_enabled=goal_enabled,
            user_facing_name=lambda _input: UPDATE_GOAL_TOOL_NAME,
        ),
    ]


def filter_goal_model_tools_for_context(
    tools: Iterable[Tool],
    context: ToolContext | Any | None,
) -> list[Tool]:
    """Drop goal tools from model-visible lists when upstream would hide them."""
    visible = goal_model_tools_visible(context)
    if visible:
        return list(tools)
    return [tool for tool in tools if tool.name not in GOAL_MODEL_TOOL_NAMES]


def goal_model_tools_visible(context: ToolContext | Any | None) -> bool:
    """Return whether goal tools should be exposed for this model context."""
    if not goal_enabled():
        return False
    if context is None:
        return False
    if _is_review_subagent_context(context):
        return False
    return _persistent_thread_id(context) is not None


def _get_goal(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    del tool_input
    try:
        thread_id = _resolve_thread_id(context)
        goal = _resolve_goal_service(context).get_goal(thread_id)
        return ToolResult(
            name=GET_GOAL_TOOL_NAME,
            output=_goal_response(goal, include_completion_budget_report=False),
        )
    except Exception as exc:  # noqa: BLE001 - tool errors are model-facing data
        return _tool_error(GET_GOAL_TOOL_NAME, exc)


def _create_goal(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        thread_id = _resolve_thread_id(context)
        objective = _require_objective(tool_input.get("objective"))
        token_budget = _parse_create_token_budget(tool_input)
        goal = _resolve_goal_service(context).create_goal(
            thread_id,
            objective,
            token_budget,
        )
        return ToolResult(
            name=CREATE_GOAL_TOOL_NAME,
            output=_goal_response(goal, include_completion_budget_report=False),
        )
    except Exception as exc:  # noqa: BLE001 - tool errors are model-facing data
        return _tool_error(CREATE_GOAL_TOOL_NAME, exc)


def _update_goal(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    try:
        thread_id = _resolve_thread_id(context)
        status = _parse_update_status(tool_input.get("status"))
        goal = _resolve_goal_service(context).update_goal(thread_id, status)
        if goal is None:
            raise GoalServiceError("cannot update goal because this thread has no goal")
        return ToolResult(
            name=UPDATE_GOAL_TOOL_NAME,
            output=_goal_response(
                goal,
                include_completion_budget_report=status is ThreadGoalStatus.COMPLETE,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - tool errors are model-facing data
        return _tool_error(UPDATE_GOAL_TOOL_NAME, exc)


def _goal_response(
    goal: ThreadGoal | None,
    *,
    include_completion_budget_report: bool,
) -> dict[str, Any]:
    dto = ThreadGoalDTO.from_model(goal).to_dict() if goal is not None else None
    remaining_tokens = None
    completion_budget_report = None

    if goal is not None and goal.token_budget is not None:
        remaining_tokens = max(goal.token_budget - goal.tokens_used, 0)
    if (
        include_completion_budget_report
        and goal is not None
        and goal.status is ThreadGoalStatus.COMPLETE
    ):
        completion_budget_report = _completion_budget_report(goal)

    return {
        "goal": dto,
        "remainingTokens": remaining_tokens,
        "completionBudgetReport": completion_budget_report,
    }


def _completion_budget_report(goal: ThreadGoal) -> str | None:
    if goal.token_budget is None and goal.time_used_seconds <= 0:
        return None
    return (
        "Goal achieved. Report final usage from this tool result's structured "
        "goal fields. If `goal.tokenBudget` is present, include token usage "
        "from `goal.tokensUsed` and `goal.tokenBudget`. If "
        "`goal.timeUsedSeconds` is greater than 0, summarize elapsed time in a "
        "concise, human-friendly form appropriate to the response language."
    )


def _resolve_goal_service(context: ToolContext | Any) -> GoalService:
    service = getattr(context, "goal_service", None)
    if service is None:
        return GoalService()
    return service


def _resolve_thread_id(context: ToolContext | Any) -> str:
    thread_id = _persistent_thread_id(context)
    if thread_id is None:
        raise GoalServiceError("Goals need a saved session before model tools can use them")
    return thread_id


def _persistent_thread_id(context: ToolContext | Any) -> str | None:
    explicit = _non_empty_str(getattr(context, "goal_thread_id", None))
    if explicit is not None:
        return explicit
    return _non_empty_str(getattr(context, "session_id", None))


def _is_review_subagent_context(context: ToolContext | Any) -> bool:
    agent_type = (_non_empty_str(getattr(context, "agent_type", None)) or "").lower()
    if agent_type in {"review", "code-reviewer"}:
        return True

    options = getattr(context, "options", None)
    query_source = (_non_empty_str(getattr(options, "query_source", None)) or "").lower()
    return query_source in {
        "agent:builtin:review",
        "agent:template:review",
        "agent:builtin:code-reviewer",
    }


def _non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_objective(value: Any) -> str:
    if not isinstance(value, str):
        raise GoalServiceError("goal objective is required")
    objective = value.strip()
    if not objective:
        raise GoalServiceError("goal objective cannot be empty")
    return objective


def _parse_create_token_budget(tool_input: dict[str, Any]) -> int | None:
    if "token_budget" not in tool_input or tool_input["token_budget"] is None:
        return None
    token_budget = int(tool_input["token_budget"])
    if token_budget <= 0:
        raise GoalServiceError("goal budgets must be positive when provided")
    return token_budget


def _parse_update_status(value: Any) -> ThreadGoalStatus:
    try:
        status = ThreadGoalStatus.from_wire(str(value))
    except ValueError as exc:
        raise GoalServiceError(
            "update_goal can only mark the existing goal complete or blocked; "
            "pause, resume, budget-limited, and usage-limited status changes "
            "are controlled by the user or system"
        ) from exc

    if status not in {ThreadGoalStatus.COMPLETE, ThreadGoalStatus.BLOCKED}:
        raise GoalServiceError(
            "update_goal can only mark the existing goal complete or blocked; "
            "pause, resume, budget-limited, and usage-limited status changes "
            "are controlled by the user or system"
        )
    return status


def _tool_error(name: str, exc: BaseException) -> ToolResult:
    return ToolResult(name=name, output={"error": str(exc)}, is_error=True)


__all__ = [
    "CREATE_GOAL_TOOL_NAME",
    "GET_GOAL_TOOL_NAME",
    "GOAL_MODEL_TOOL_NAMES",
    "UPDATE_GOAL_TOOL_NAME",
    "filter_goal_model_tools_for_context",
    "goal_model_tools_visible",
    "make_goal_model_tools",
]
