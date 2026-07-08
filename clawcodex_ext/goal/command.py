"""Upstream-compatible `/goal` user command."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.command_system.types import (
    InteractiveCommand,
    InteractiveOutcome,
    UIOption,
)

from .gate import goal_enabled
from .files import objective_text_for_edit
from .model import ThreadGoalStatus
from .protocol import (
    ThreadGoalClearParams,
    ThreadGoalDTO,
    ThreadGoalGetParams,
    ThreadGoalProtocol,
    ThreadGoalSetParams,
)
from .service import KEEP_TOKEN_BUDGET, GoalServiceError, goal_thread_id_from_context

GOAL_USAGE = "/goal [<objective>|clear|edit|pause|resume]"


class GoalCommand(InteractiveCommand):
    """Feature-gated upstream-compatible `/goal` command."""

    async def run(self, args: str, context: Any) -> InteractiveOutcome:
        if not goal_enabled():
            return InteractiveOutcome(message="Goal mode is disabled.", display="system")

        api = _goal_api_from_context(context)
        thread_id = goal_thread_id_from_context(context)
        command = args.strip()

        try:
            if not command:
                return _goal_summary(api, thread_id, context)

            lowered = command.lower()
            if lowered == "clear":
                return _clear_goal(api, thread_id, context)
            if lowered == "pause":
                return _set_goal_status(api, thread_id, ThreadGoalStatus.PAUSED, context)
            if lowered == "resume":
                return _set_goal_status(api, thread_id, ThreadGoalStatus.ACTIVE, context)
            if lowered == "edit":
                return await _edit_goal(api, thread_id, context)

            return await _set_goal_objective(api, thread_id, command, context)
        except GoalServiceError as exc:
            return InteractiveOutcome(message=str(exc), display="system")


GOAL_COMMAND = GoalCommand(
    name="goal",
    description="Manage an upstream-compatible long-running goal.",
    argument_hint="[<objective>|clear|edit|pause|resume]",
    aliases=["g"],
    is_enabled=goal_enabled,
)


def _goal_api_from_context(context: Any) -> ThreadGoalProtocol:
    api = getattr(context, "goal_api", None)
    tool_context = getattr(context, "tool_context", None)
    if api is None:
        service = getattr(context, "goal_service", None) or getattr(
            tool_context,
            "goal_service",
            None,
        )
        events = getattr(context, "goal_events", None)
        kwargs: dict[str, Any] = {}
        if service is not None:
            kwargs["service"] = service
        if events is not None:
            kwargs["events"] = events
        api = ThreadGoalProtocol(**kwargs)

    try:
        context.goal_api = api
        context.goal_service = api.service
        context.goal_events = api.events
    except Exception:
        pass
    if tool_context is not None:
        try:
            tool_context.goal_service = api.service
        except Exception:
            pass
    return api


def _goal_summary(
    api: ThreadGoalProtocol,
    thread_id: str,
    context: Any | None = None,
) -> InteractiveOutcome:
    response = api.thread_goal_get(ThreadGoalGetParams(thread_id=thread_id))
    if response.goal is None:
        _sync_app_goal_status(None, context)
        return InteractiveOutcome(
            message=f"{GOAL_USAGE}\nNo goal is currently set.",
            display="system",
        )
    _sync_app_goal_status(response.goal, context)
    return InteractiveOutcome(
        message=_format_goal_summary(response.goal),
        display="system",
    )


async def _set_goal_objective(
    api: ThreadGoalProtocol,
    thread_id: str,
    objective: str,
    context: Any,
) -> InteractiveOutcome:
    current = api.thread_goal_get(ThreadGoalGetParams(thread_id=thread_id)).goal
    if current is not None:
        if current.status is not ThreadGoalStatus.COMPLETE:
            choice = await context.ui.select(
                "Replace goal?",
                [
                    UIOption(
                        "replace",
                        "Replace current goal",
                        "Set the new objective and start it now",
                    ),
                    UIOption("cancel", "Cancel", "Keep the current goal"),
                ],
            )
            if choice != "replace":
                return InteractiveOutcome.skip()
        api.thread_goal_clear(ThreadGoalClearParams(thread_id=thread_id))

    response = api.thread_goal_set(
        ThreadGoalSetParams(
            thread_id=thread_id,
            objective=objective,
            status=ThreadGoalStatus.ACTIVE,
        )
    )
    return _goal_status_outcome(response.goal, context)


async def _edit_goal(
    api: ThreadGoalProtocol,
    thread_id: str,
    context: Any,
) -> InteractiveOutcome:
    current = api.thread_goal_get(ThreadGoalGetParams(thread_id=thread_id)).goal
    if current is None:
        return InteractiveOutcome(
            message=f"No goal is currently set.\n{GOAL_USAGE}",
            display="system",
        )

    edited = await context.ui.prompt_text(
        "Edit goal",
        default=objective_text_for_edit(
            current.objective,
            codex_home=getattr(api.service, "codex_home", None),
        ),
        placeholder="Type a goal objective and press Enter",
    )
    if edited is None:
        return InteractiveOutcome.skip()

    if current.status in {
        ThreadGoalStatus.BUDGET_LIMITED,
        ThreadGoalStatus.COMPLETE,
    }:
        api.thread_goal_clear(ThreadGoalClearParams(thread_id=thread_id))
        response = api.thread_goal_set(
            ThreadGoalSetParams(
                thread_id=thread_id,
                objective=edited,
                status=ThreadGoalStatus.ACTIVE,
                token_budget=current.token_budget,
            )
        )
    else:
        response = api.thread_goal_set(
            ThreadGoalSetParams(
                thread_id=thread_id,
                objective=edited,
                status=current.status,
                token_budget=current.token_budget,
            )
        )
    return _goal_status_outcome(response.goal, context)


def _clear_goal(
    api: ThreadGoalProtocol,
    thread_id: str,
    context: Any | None = None,
) -> InteractiveOutcome:
    response = api.thread_goal_clear(ThreadGoalClearParams(thread_id=thread_id))
    if response.cleared:
        _sync_app_goal_status(None, context)
        return InteractiveOutcome(message="Goal cleared", display="system")
    return InteractiveOutcome(
        message="No goal to clear\nThis thread does not currently have a goal.",
        display="system",
    )


def _set_goal_status(
    api: ThreadGoalProtocol,
    thread_id: str,
    status: ThreadGoalStatus,
    context: Any | None = None,
) -> InteractiveOutcome:
    response = api.thread_goal_set(
        ThreadGoalSetParams(
            thread_id=thread_id,
            status=status,
            token_budget=KEEP_TOKEN_BUDGET,
        )
    )
    return _goal_status_outcome(response.goal, context)


def _goal_status_outcome(
    goal: ThreadGoalDTO,
    context: Any | None = None,
) -> InteractiveOutcome:
    _sync_app_goal_status(goal, context)
    return InteractiveOutcome(
        message=f"Goal {_goal_status_label(goal.status)}\n{_goal_usage_summary(goal)}",
        display="system",
        should_query=goal.status is ThreadGoalStatus.ACTIVE,
    )


def _format_goal_summary(goal: ThreadGoalDTO) -> str:
    lines = [
        "Goal",
        f"Status: {_goal_status_label(goal.status)}",
        f"Objective: {goal.objective}",
        f"Time used: {goal.time_used_seconds}s",
        f"Tokens used: {goal.tokens_used}",
    ]
    if goal.token_budget is not None:
        lines.append(f"Token budget: {goal.token_budget}")
    lines.append("")
    lines.append(f"Commands: {_goal_commands_for_status(goal.status)}")
    return "\n".join(lines)


def _goal_usage_summary(goal: ThreadGoalDTO) -> str:
    if goal.token_budget is not None:
        return f"{goal.tokens_used} / {goal.token_budget} tokens"
    return f"{goal.time_used_seconds}s"


def _goal_commands_for_status(status: ThreadGoalStatus) -> str:
    if status is ThreadGoalStatus.ACTIVE:
        return "/goal edit, /goal pause, /goal clear"
    if status in {
        ThreadGoalStatus.PAUSED,
        ThreadGoalStatus.BLOCKED,
        ThreadGoalStatus.USAGE_LIMITED,
    }:
        return "/goal edit, /goal resume, /goal clear"
    return "/goal edit, /goal clear"


def _goal_status_label(status: ThreadGoalStatus) -> str:
    return {
        ThreadGoalStatus.ACTIVE: "active",
        ThreadGoalStatus.PAUSED: "paused",
        ThreadGoalStatus.BLOCKED: "blocked",
        ThreadGoalStatus.USAGE_LIMITED: "usage limited",
        ThreadGoalStatus.BUDGET_LIMITED: "limited by budget",
        ThreadGoalStatus.COMPLETE: "complete",
    }[status]


def _sync_app_goal_status(goal: ThreadGoalDTO | None, context: Any | None) -> None:
    if context is None:
        return
    app_state = getattr(context, "app_state", None)
    if app_state is None:
        return
    setter = getattr(app_state, "set_goal_status", None)
    if not callable(setter):
        return
    setter(goal.to_dict() if goal is not None else None)


__all__ = ["GOAL_COMMAND", "GOAL_USAGE", "GoalCommand"]
