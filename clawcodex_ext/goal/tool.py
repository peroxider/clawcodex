"""Model-callable ``Goal`` tool — exposes goal state to the assistant.

The tool has two actions, mirroring the upstream TS ``GoalTool``
interface (FEATURE_PLAN.md §2.6.7):

* ``get`` — return the current :class:`GoalState` summary. Read-only.
* ``update`` — mutate the goal. Accepted fields:

  - ``status``: one of ``active``, ``paused``, ``complete``,
    ``blocked``, ``usage_limited`` (``budget_limited`` is set
    automatically by the controller, not by the model).
  - ``reason``: free-form blocker reason (only meaningful when
    ``status == "blocked"``); routed through the consecutive-match
    counter in :func:`record_blocker`.
  - ``objective``: replace the goal's objective text (equivalent to
    the user invoking ``/goal <new>``).

The tool is deliberately *not* concurrency-safe: every call writes
through the registry's RLock, but parallel calls would race the
state machine.
"""

from __future__ import annotations

import logging
from typing import Any

from src.tool_system.build_tool import build_tool
from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from clawcodex_ext.tool_system.protocol import ToolResult

from . import prompts
from .controller import GoalController
from .state_machine import (
    GoalObjectiveTooLong,
    GoalStateError,
    record_blocker,
)
from .types import MAX_OBJECTIVE_CHARS, GoalStatus

logger = logging.getLogger(__name__)


# Allowed status transitions for the model-driven ``update`` action.
# ``budget_limited`` and ``max_turns`` are NOT in this list because
# those states are managed by the controller's auto-pump machinery —
# the model shouldn't be able to bypass the budget check.
_UPDATE_STATUS_VALUES: tuple[str, ...] = (
    GoalStatus.ACTIVE.value,
    GoalStatus.PAUSED.value,
    GoalStatus.COMPLETE.value,
    GoalStatus.BLOCKED.value,
    GoalStatus.USAGE_LIMITED.value,
)


def _controller_for(context: ToolContext) -> GoalController:
    """Build a transient controller bound to ``context.session_id``."""
    sid = getattr(context, "session_id", None)
    ctrl = GoalController(session_id=sid)
    if sid:
        ctrl.bind(sid)
    return ctrl


def _goal_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    """Dispatch the two ``action`` variants of the goal tool."""
    action = tool_input.get("action")
    if not isinstance(action, str) or not action:
        raise ToolInputError("action must be a non-empty string")
    if action == "get":
        return _goal_get(tool_input, context)
    if action == "update":
        return _goal_update(tool_input, context)
    raise ToolInputError(
        f"unknown action {action!r}; expected 'get' or 'update'"
    )


def _goal_get(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    state = _controller_for(context).get_state()
    if state is None:
        return ToolResult(
            name="Goal",
            output={
                "hasGoal": False,
                "objective": None,
                "status": None,
                "tokensUsed": 0,
                "tokenBudget": None,
                "turnsExecuted": 0,
                "blockedAttempts": 0,
                "lastBlockReason": None,
            },
        )
    return ToolResult(
        name="Goal",
        output={
            "hasGoal": True,
            "objective": state.objective,
            "status": state.status.value,
            "tokensUsed": state.tokens_used,
            "tokenBudget": state.token_budget,
            "turnsExecuted": state.turns_executed,
            "blockedAttempts": state.blocked_attempts,
            "lastBlockReason": state.last_block_reason,
            "pill": prompts.format_pill(state),
        },
    )


def _goal_update(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    controller = _controller_for(context)
    if controller.get_state() is None:
        raise ToolInputError(
            "no active goal; the user must run /goal <objective> first"
        )

    new_objective = tool_input.get("objective")
    if new_objective is not None:
        if not isinstance(new_objective, str):
            raise ToolInputError("objective must be a string when provided")
        text = new_objective.strip()
        if not text:
            raise ToolInputError("objective must be a non-empty string")
        if len(text) > MAX_OBJECTIVE_CHARS:
            raise ToolInputError(
                f"objective is {len(text)} chars; max is {MAX_OBJECTIVE_CHARS}"
            )
        # Re-set the goal through the controller so persistence +
        # meta-message broadcast run as a single atomic write.
        controller.set_new_goal(text)
        return ToolResult(
            name="Goal",
            output={
                "success": True,
                "action": "update",
                "changed": "objective",
                "state": _state_summary(controller.get_state()),
            },
        )

    status_raw = tool_input.get("status")
    if status_raw is None:
        raise ToolInputError(
            "update requires either 'objective' or 'status'"
        )
    if not isinstance(status_raw, str):
        raise ToolInputError("status must be a string")
    if status_raw not in _UPDATE_STATUS_VALUES:
        raise ToolInputError(
            f"status {status_raw!r} is not a model-settable state; "
            f"allowed: {', '.join(_UPDATE_STATUS_VALUES)}"
        )

    try:
        if status_raw == GoalStatus.PAUSED.value:
            new_state = controller.pause()
        elif status_raw == GoalStatus.ACTIVE.value:
            new_state = controller.resume()
        elif status_raw == GoalStatus.COMPLETE.value:
            new_state = controller.complete()
        elif status_raw == GoalStatus.USAGE_LIMITED.value:
            new_state = controller.mark_usage_limited()
        elif status_raw == GoalStatus.BLOCKED.value:
            reason = tool_input.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ToolInputError(
                    "status='blocked' requires a non-empty 'reason' string"
                )
            # Route through the consecutive-match counter. The
            # controller returns ``(state, transitioned)``; we
            # surface only the new state to the model.
            new_state, _ = controller.record_blocker(reason.strip())
        else:  # pragma: no cover — guarded by the enum check above
            raise ToolInputError(f"unsupported status: {status_raw}")
    except GoalStateError as exc:
        return ToolResult(
            name="Goal",
            output={"success": False, "action": "update", "error": str(exc)},
            is_error=True,
        )

    return ToolResult(
        name="Goal",
        output={
            "success": True,
            "action": "update",
            "changed": "status",
            "newStatus": new_state.status.value,
            "state": _state_summary(new_state),
        },
    )


def _state_summary(state) -> dict[str, Any]:
    if state is None:
        return {"hasGoal": False}
    return {
        "hasGoal": True,
        "objective": state.objective,
        "status": state.status.value,
        "tokensUsed": state.tokens_used,
        "tokenBudget": state.token_budget,
        "turnsExecuted": state.turns_executed,
        "blockedAttempts": state.blocked_attempts,
        "lastBlockReason": state.last_block_reason,
    }


def _classifier_input(input_data: dict[str, Any]) -> str:
    """Compact classifier input for the auto-classifier subsystem."""
    action = (input_data or {}).get("action") or ""
    if action == "update":
        status = (input_data or {}).get("status") or ""
        reason = (input_data or {}).get("reason") or ""
        return f"update {status} {reason}".strip()
    return f"get {action}".strip()


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


GoalTool = build_tool(
    name="Goal",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "update"],
                "description": (
                    "'get' returns the current goal summary; "
                    "'update' mutates the goal via 'objective' or "
                    "'status' (+ 'reason' for blocked)."
                ),
            },
            "objective": {
                "type": "string",
                "description": (
                    "Replacement objective text. Only used when "
                    "action='update'."
                ),
            },
            "status": {
                "type": "string",
                "enum": list(_UPDATE_STATUS_VALUES),
                "description": (
                    "New status. Only used when action='update'. "
                    "budget_limited and max_turns are managed by "
                    "the controller and cannot be set here."
                ),
            },
            "reason": {
                "type": "string",
                "description": (
                    "Blocker reason (required when status='blocked'). "
                    "Same reason 3 times in a row flips the goal to "
                    "'blocked'."
                ),
            },
        },
        "required": ["action"],
    },
    call=_goal_call,
    prompt=(
        "Use this tool to read or mutate the long-running goal that the "
        "user set with `/goal`. Two actions:\n\n"
        "* `get` — returns the current objective, status, tokens "
        "used / budget, turn count, and active-goal blocker streak. "
        "Read-only.\n"
        "* `update` — replaces the objective (`objective` field) or "
        "transitions the status. Allowed statuses: `active`, `paused`, "
        "`complete`, `usage_limited`, `blocked`. `budget_limited` and "
        "`max_turns` are managed automatically by the controller — "
        "do not set them. When status='blocked', supply `reason` "
        "(free-form, e.g. 'no API key', 'compilation error'); the "
        "same reason reported three consecutive times flips the "
        "goal into the blocked state.\n\n"
        "Always perform the Completion Audit before calling "
        "`update` with status='complete'."
    ),
    description="Read or update the active long-running goal.",
    strict=True,
    max_result_size_chars=20_000,
    is_read_only=lambda input_data: (input_data or {}).get("action") == "get",
    is_concurrency_safe=lambda _input: False,
    is_destructive=lambda _input: False,
    to_auto_classifier_input=_classifier_input,
    user_facing_name=lambda input_data: (
        "GetGoal" if (input_data or {}).get("action") == "get" else "UpdateGoal"
    ),
    get_tool_use_summary=lambda input_data: (
        "Get current goal" if (input_data or {}).get("action") == "get"
        else f"Update goal ({((input_data or {}).get('status') or (input_data or {}).get('objective') or '')[:60]})"
    ),
    get_activity_description=lambda input_data: (
        "Reading goal state" if (input_data or {}).get("action") == "get"
        else "Updating goal"
    ),
)


__all__ = ["GoalTool"]
