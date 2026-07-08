"""Goal runtime continuation and lifecycle tests for F-122 Spec 5."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from clawcodex_ext.goal.model import ThreadGoalStatus
from clawcodex_ext.goal.runtime import (
    BUDGET_LIMIT_STEERING_MARKER,
    CONTINUATION_STEERING_MARKER,
    OBJECTIVE_UPDATED_STEERING_MARKER,
    GoalRuntime,
)
from clawcodex_ext.goal.accounting import (
    BudgetLimitedGoalDisposition,
    GoalAccountingState,
)
from clawcodex_ext.goal.service import GoalService
from clawcodex_ext.goal.store import GoalStore, goals_db_filename
from clawcodex_ext.providers.base import ChatResponse
from clawcodex_ext.tool_system.context import ToolContext
from clawcodex_ext.tool_system.defaults import build_default_registry
from clawcodex_ext.types.messages import UserMessage
from src.query.agent_loop_compat import run_query_as_agent_loop


class FakeClock:
    def __init__(self) -> None:
        self._now = 1_000.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _run(coro):
    try:
        previous = asyncio.get_event_loop()
    except RuntimeError:
        previous = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        if previous is not None and not previous.is_closed():
            asyncio.set_event_loop(previous)
        else:
            asyncio.set_event_loop(asyncio.new_event_loop())


def make_service(tmp_path: Path) -> GoalService:
    return GoalService(store=GoalStore(tmp_path / goals_db_filename()))


def make_runtime(
    tmp_path: Path,
    *,
    thread_id: str = "thread-1",
    accounting_state: GoalAccountingState | None = None,
) -> tuple[GoalService, GoalRuntime]:
    service = make_service(tmp_path)
    runtime = GoalRuntime(
        thread_id=thread_id,
        service=service,
        accounting_state=accounting_state,
    )
    service.register_runtime(runtime)
    return service, runtime


def test_registered_runtime_service_mutations_control_idle_continuation(
    tmp_path: Path,
) -> None:
    service, runtime = make_runtime(tmp_path)

    goal = service.create_goal("thread-1", "external create")
    active_request = runtime.continue_if_idle()
    blocked = service.update_goal(
        "thread-1",
        ThreadGoalStatus.BLOCKED,
        expected_goal_id=goal.goal_id,
    )
    blocked_request = runtime.continue_if_idle()
    resumed = service.resume_goal("thread-1")
    resumed_request = runtime.continue_if_idle()
    cleared = service.clear_goal("thread-1")

    assert active_request is not None
    assert active_request.expected_goal_id == goal.goal_id
    assert blocked is not None
    assert blocked.status is ThreadGoalStatus.BLOCKED
    assert blocked_request is None
    assert resumed is not None
    assert resumed.status is ThreadGoalStatus.ACTIVE
    assert resumed_request is not None
    assert resumed_request.expected_goal_id == resumed.goal_id
    assert cleared is True
    assert runtime.continue_if_idle() is None


def test_restore_after_resume_accounts_idle_active_goal_time(tmp_path: Path) -> None:
    clock = FakeClock()
    service, runtime = make_runtime(
        tmp_path,
        accounting_state=GoalAccountingState(clock=clock),
    )
    goal = service.replace_goal("thread-1", "resume accounting")

    runtime.restore_after_resume()
    clock.advance(7)
    progress = runtime.account_idle_goal_progress(BudgetLimitedGoalDisposition.KEEP_ACTIVE)

    stored = service.get_goal("thread-1")
    assert progress is not None
    assert progress.goal_id == goal.goal_id
    assert stored is not None
    assert stored.time_used_seconds == 7
    assert stored.tokens_used == 0
    assert stored.status is ThreadGoalStatus.ACTIVE


def test_continue_if_idle_starts_only_for_idle_active_goal(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    goal = service.replace_goal("thread-1", "ship runtime")

    request = runtime.continue_if_idle()

    assert request is not None
    assert request.expected_goal_id == goal.goal_id
    assert request.messages[0].isMeta is True
    assert CONTINUATION_STEERING_MARKER in str(request.messages[0].content)

    runtime.on_turn_start("turn-1", plan_mode=False)

    assert runtime.continue_if_idle() is None


def test_pause_and_clear_invalidate_pending_continuation(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "do not continue after pause")
    paused_request = runtime.continue_if_idle()

    service.pause_goal("thread-1")

    assert paused_request is not None
    assert runtime.claim_continuation(paused_request) is False
    assert runtime.continue_if_idle() is None

    service.resume_goal("thread-1")
    cleared_request = runtime.continue_if_idle()
    service.clear_goal("thread-1")

    assert cleared_request is not None
    assert runtime.claim_continuation(cleared_request) is False
    assert runtime.continue_if_idle() is None


def test_replace_invalidates_old_pending_continuation(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "old objective")
    old_request = runtime.continue_if_idle()

    new_goal = service.replace_goal("thread-1", "new objective")
    new_request = runtime.continue_if_idle()

    assert old_request is not None
    assert runtime.claim_continuation(old_request) is False
    assert new_request is not None
    assert new_request.expected_goal_id == new_goal.goal_id
    assert "new objective" in str(new_request.messages[0].content)
    assert "old objective" not in str(new_request.messages[0].content)


def test_tool_finish_accounts_usage_and_reports_budget_limit_once(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    goal = service.replace_goal("thread-1", "budget", token_budget=10)
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage(
        "turn-1",
        {"input_tokens": 6, "cache_read_input_tokens": 1, "output_tokens": 5},
    )

    first = runtime.on_tool_finish(
        "turn-1",
        tool_name="Bash",
        call_id="call-1",
        handler_executed=True,
    )
    second = runtime.on_tool_finish(
        "turn-1",
        tool_name="Read",
        call_id="call-2",
        handler_executed=True,
    )

    limited = service.get_goal("thread-1")
    assert limited is not None
    assert limited.goal_id == goal.goal_id
    assert limited.status is ThreadGoalStatus.BUDGET_LIMITED
    assert limited.tokens_used == 10
    assert len(first) == 1
    assert BUDGET_LIMIT_STEERING_MARKER in str(first[0].content)
    assert second == []
    assert runtime.continue_if_idle() is None


def test_expected_goal_id_prevents_old_turn_usage_from_writing_new_goal(
    tmp_path: Path,
) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "old", token_budget=10)
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 10, "output_tokens": 1})

    new_goal = service.replace_goal("thread-1", "new", token_budget=100)
    runtime.on_tool_finish(
        "turn-1",
        tool_name="Bash",
        call_id="call-1",
        handler_executed=True,
    )

    assert service.get_goal("thread-1") == new_goal


def test_objective_update_during_turn_queues_objective_updated_steering(
    tmp_path: Path,
) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "old objective")
    runtime.on_turn_start("turn-1", plan_mode=False)

    service.set_goal("thread-1", "new <objective>")
    pending = runtime.consume_pending_steering_messages()

    assert len(pending) == 1
    assert OBJECTIVE_UPDATED_STEERING_MARKER in str(pending[0].content)
    assert "new &lt;objective&gt;" in str(pending[0].content)
    assert runtime.consume_pending_steering_messages() == []


def test_turn_abort_pauses_active_goal_and_stops_continuation(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "abort me")
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 2, "output_tokens": 3})

    runtime.on_turn_abort("turn-1")

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.PAUSED
    assert goal.tokens_used == 5
    assert runtime.continue_if_idle() is None


def test_turn_error_and_usage_limit_stop_active_goal(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "error")
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 2, "output_tokens": 3})

    runtime.on_turn_error("turn-1", RuntimeError("model crashed"))

    blocked = service.get_goal("thread-1")
    assert blocked is not None
    assert blocked.status is ThreadGoalStatus.BLOCKED
    assert runtime.continue_if_idle() is None

    service.replace_goal("thread-1", "usage")
    runtime.on_turn_start("turn-2", plan_mode=False)
    runtime.on_turn_error("turn-2", RuntimeError("usage limit exceeded"))

    limited = service.get_goal("thread-1")
    assert limited is not None
    assert limited.status is ThreadGoalStatus.USAGE_LIMITED
    assert runtime.continue_if_idle() is None


def test_usage_limit_error_promotes_budget_limited_goal_to_usage_limited(
    tmp_path: Path,
) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "budget then usage limit", token_budget=1)
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 1, "output_tokens": 0})

    budget_prompt = runtime.on_tool_finish(
        "turn-1",
        tool_name="Bash",
        call_id="call-1",
        handler_executed=True,
    )
    runtime.on_turn_error("turn-1", RuntimeError("usage limit exceeded"))

    goal = service.get_goal("thread-1")
    assert budget_prompt
    assert goal is not None
    assert goal.status is ThreadGoalStatus.USAGE_LIMITED
    assert runtime.continue_if_idle() is None


def test_agent_loop_continues_active_goal_until_update_goal_complete(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.replace_goal("thread-1", "finish via continuation")
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    registry = build_default_registry()
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.side_effect = [
        ChatResponse(
            content="Initial turn done.",
            model="test",
            usage={"input_tokens": 2, "output_tokens": 2},
            finish_reason="end_turn",
            tool_uses=None,
        ),
        ChatResponse(
            content="Completing the goal.",
            model="test",
            usage={"input_tokens": 4, "output_tokens": 1},
            finish_reason="tool_use",
            tool_uses=[
                {
                    "id": "toolu_goal",
                    "name": "update_goal",
                    "input": {"status": "complete"},
                }
            ],
        ),
        ChatResponse(
            content="Goal complete.",
            model="test",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="end_turn",
            tool_uses=None,
        ),
    ]

    result = _run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="start")],
            provider=provider,
            tool_registry=registry,
            tool_context=context,
            system_prompt="You are helpful.",
            max_turns=5,
        )
    )

    goal = service.get_goal("thread-1")
    second_call_messages = provider.chat.call_args_list[1].args[0]
    assert goal is not None
    assert goal.status is ThreadGoalStatus.COMPLETE
    assert result.response_text == "Goal complete."
    assert provider.chat.call_count == 3
    assert any(
        CONTINUATION_STEERING_MARKER in str(message.get("content", ""))
        for message in second_call_messages
        if message.get("role") == "user"
    )
