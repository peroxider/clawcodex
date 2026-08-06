"""Goal runtime continuation and lifecycle tests for Spec 5."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clawcodex_ext.goal.evaluator import GoalEvaluationError
from clawcodex_ext.goal.model import GoalCompletionMode, ThreadGoalStatus
from clawcodex_ext.goal.runtime import (
    BUDGET_LIMIT_STEERING_MARKER,
    CONTINUATION_STEERING_MARKER,
    OBJECTIVE_UPDATED_STEERING_MARKER,
    GoalRuntime,
    restore_goal_runtime_after_session_resume,
)
from clawcodex_ext.goal.steering import EVALUATOR_CONTINUATION_MARKER
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


def test_session_resume_keeps_condition_but_resets_progress(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    goal = service.replace_goal("thread-1", "keep this condition")
    service.account_usage(
        "thread-1",
        expected_goal_id=goal.goal_id,
        token_delta=17,
        elapsed_seconds=6,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )

    runtime = restore_goal_runtime_after_session_resume(context)

    restored = service.get_goal("thread-1")
    assert runtime is not None
    assert runtime.thread_id == "thread-1"
    assert restored is not None
    assert restored.goal_id == goal.goal_id
    assert restored.objective == "keep this condition"
    assert restored.status is ThreadGoalStatus.ACTIVE
    assert restored.tokens_used == 0
    assert restored.time_used_seconds == 0


def test_session_resume_does_not_restore_achieved_evaluator_goal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    goal = service.replace_goal(
        "thread-1",
        "already achieved",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    service.update_goal(
        "thread-1",
        ThreadGoalStatus.COMPLETE,
        expected_goal_id=goal.goal_id,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )

    runtime = restore_goal_runtime_after_session_resume(context)

    assert runtime is not None
    assert service.get_goal("thread-1") is None


def test_completion_accounts_triggering_turn_before_status_change(tmp_path: Path) -> None:
    clock = FakeClock()
    service, runtime = make_runtime(
        tmp_path,
        accounting_state=GoalAccountingState(clock=clock),
    )
    goal = service.replace_goal("thread-1", "finish with accounting")
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 3, "output_tokens": 2})
    clock.advance(7)

    completed = service.update_goal(
        "thread-1",
        ThreadGoalStatus.COMPLETE,
        expected_goal_id=goal.goal_id,
    )
    runtime.on_turn_stop("turn-1")

    assert completed is not None
    assert completed.status is ThreadGoalStatus.COMPLETE
    assert completed.tokens_used == 5
    assert completed.time_used_seconds == 7


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
    original = service.replace_goal("thread-1", "old objective")
    runtime.on_turn_start("turn-1", plan_mode=False)

    replacement = service.replace_goal("thread-1", "new <objective>")
    pending = runtime.consume_pending_steering_messages()

    assert replacement.goal_id != original.goal_id
    assert runtime.goal_id_at_turn_start("turn-1") == original.goal_id
    assert len(pending) == 1
    assert OBJECTIVE_UPDATED_STEERING_MARKER in str(pending[0].content)
    assert "new &lt;objective&gt;" in str(pending[0].content)
    assert runtime.consume_pending_steering_messages() == []


def test_turn_abort_keeps_active_goal_for_later_resume(tmp_path: Path) -> None:
    service, runtime = make_runtime(tmp_path)
    service.replace_goal("thread-1", "abort me")
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 2, "output_tokens": 3})

    runtime.on_turn_abort("turn-1")

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.tokens_used == 5
    assert runtime.continue_if_idle() is not None


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


def test_turn_error_keeps_evaluator_goal_active_for_retry(tmp_path: Path) -> None:
    clock = FakeClock()
    service, runtime = make_runtime(
        tmp_path,
        accounting_state=GoalAccountingState(clock=clock),
    )
    service.replace_goal(
        "thread-1",
        "retry after provider error",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    runtime.on_turn_start("turn-1", plan_mode=False)
    runtime.on_token_usage("turn-1", {"input_tokens": 2, "output_tokens": 3})

    runtime.on_turn_error("turn-1", RuntimeError("model crashed"))

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.tokens_used == 5
    clock.advance(4)
    runtime.account_idle_goal_progress(BudgetLimitedGoalDisposition.KEEP_ACTIVE)
    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.time_used_seconds == 4
    assert runtime.continue_if_idle() is not None


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
    # The two responses through the completion tool are goal work.  The
    # final explanatory response happens after completion and is excluded.
    assert goal.tokens_used == 9
    assert result.response_text == "Goal complete."
    assert provider.chat.call_count == 3
    assert any(
        CONTINUATION_STEERING_MARKER in str(message.get("content", ""))
        for message in second_call_messages
        if message.get("role") == "user"
    )


def test_agent_loop_uses_independent_evaluator_until_condition_is_met(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "produce verified evidence",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.side_effect = [
        ChatResponse(
            content="I made partial progress.",
            model="test",
            usage={"input_tokens": 2, "output_tokens": 2},
            finish_reason="end_turn",
            tool_uses=None,
        ),
        ChatResponse(
            content="The verified evidence is now present.",
            model="test",
            usage={"input_tokens": 3, "output_tokens": 1},
            finish_reason="end_turn",
            tool_uses=None,
        ),
    ]
    provider.chat_async = AsyncMock(
        side_effect=[
            ChatResponse(
                content='{"met": false, "reason": "Verification evidence is missing."}',
                model="evaluator",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
            ),
            ChatResponse(
                content='{"met": true, "reason": "The transcript now contains verification."}',
                model="evaluator",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
            ),
        ]
    )
    persisted_messages: list[object] = []

    result = _run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="start")],
            provider=provider,
            tool_registry=build_default_registry(),
            tool_context=context,
            system_prompt="You are helpful.",
            max_turns=5,
            on_message=persisted_messages.append,
        )
    )

    goal = service.get_goal("thread-1")
    second_call_messages = provider.chat.call_args_list[1].args[0]
    assert goal is not None
    assert goal.status is ThreadGoalStatus.COMPLETE
    assert goal.evaluation_count == 2
    assert goal.last_evaluation_reason == "The transcript now contains verification."
    assert goal.tokens_used == 12
    assert result.response_text == "The verified evidence is now present."
    assert result.usage == {"input_tokens": 7, "output_tokens": 5}
    assert provider.chat.call_count == 2
    assert provider.chat_async.await_count == 2
    assert [
        getattr(message, "subtype", None)
        for message in persisted_messages
        if getattr(message, "role", None) == "system"
    ] == ["goal_evaluation", "goal_achieved"]
    achieved_notice = next(
        message
        for message in persisted_messages
        if getattr(message, "subtype", None) == "goal_achieved"
    )
    assert "2 turns" in str(achieved_notice.content)
    assert "12 tokens" in str(achieved_notice.content)
    assert achieved_notice.data["state"] == "achieved"
    assert achieved_notice.data["met"] is True
    assert achieved_notice.data["turns"] == 2
    assert any(
        EVALUATOR_CONTINUATION_MARKER in str(message.get("content", ""))
        for message in second_call_messages
        if message.get("role") == "user"
    )


def test_evaluator_only_continuation_respects_explicit_max_turns(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "stop at the explicit safety cap",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.side_effect = [
        ChatResponse(
            content="The condition is not met yet.",
            model="test",
            usage={"input_tokens": 2, "output_tokens": 1},
            finish_reason="end_turn",
            tool_uses=None,
        ),
        ChatResponse(
            content="The condition is still not met.",
            model="test",
            usage={"input_tokens": 3, "output_tokens": 1},
            finish_reason="end_turn",
            tool_uses=None,
        ),
    ]
    provider.chat_async = AsyncMock(
        side_effect=[
            ChatResponse(
                content='{"met": false, "reason": "More work is required."}',
                model="evaluator",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
            ),
            ChatResponse(
                content='{"met": false, "reason": "The condition remains unmet."}',
                model="evaluator",
                usage={"input_tokens": 1, "output_tokens": 1},
                finish_reason="end_turn",
            ),
        ]
    )

    result = _run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="start")],
            provider=provider,
            tool_registry=build_default_registry(),
            tool_context=context,
            system_prompt="You are helpful.",
            max_turns=2,
        )
    )

    goal = service.get_goal("thread-1")
    assert result.response_text == "[Max tool turns reached]"
    assert result.num_turns == 2
    assert result.usage == {"input_tokens": 7, "output_tokens": 4}
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 2
    assert provider.chat.call_count == 2
    assert provider.chat_async.await_count == 2


def test_goal_evaluator_failure_is_explicit_and_does_not_spin(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "evaluate safely",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.return_value = ChatResponse(
        content="Main turn finished.",
        model="test",
        usage={"input_tokens": 2, "output_tokens": 2},
        finish_reason="end_turn",
        tool_uses=None,
    )
    provider.chat_async = AsyncMock(side_effect=RuntimeError("evaluator unavailable"))

    with pytest.raises(GoalEvaluationError, match="evaluator unavailable"):
        _run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="start")],
                provider=provider,
                tool_registry=build_default_registry(),
                tool_context=context,
                system_prompt="You are helpful.",
                max_turns=5,
            )
        )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 0
    assert provider.chat.call_count == 1
    assert provider.chat_async.await_count == 1


def test_goal_evaluator_invalid_response_usage_is_accounted(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "evaluate safely",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.return_value = ChatResponse(
        content="Main turn finished.",
        model="test",
        usage={"input_tokens": 2, "output_tokens": 2},
        finish_reason="end_turn",
        tool_uses=None,
    )
    provider.chat_async = AsyncMock(
        return_value=ChatResponse(
            content="not json",
            model="evaluator",
            usage={"input_tokens": 3, "output_tokens": 1},
            finish_reason="end_turn",
        )
    )
    persisted_messages: list[object] = []

    with pytest.raises(GoalEvaluationError, match="not valid JSON") as raised:
        _run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="start")],
                provider=provider,
                tool_registry=build_default_registry(),
                tool_context=context,
                system_prompt="You are helpful.",
                max_turns=5,
                on_message=persisted_messages.append,
            )
        )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.tokens_used == 8
    error_notice = next(
        message
        for message in persisted_messages
        if getattr(message, "subtype", None) == "goal_evaluator_error"
    )
    assert getattr(error_notice, "usage", None) == {
        "input_tokens": 3,
        "output_tokens": 1,
    }
    assert error_notice.data["state"] == "active"
    assert error_notice.data["met"] is None
    assert error_notice.data["goalId"] == goal.goal_id
    assert raised.value.aggregate_usage == {
        "input_tokens": 5,
        "output_tokens": 3,
    }
    assert raised.value.num_turns == 1


def test_goal_model_api_error_stops_run_and_keeps_goal_active(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "retry after the provider recovers",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = RuntimeError("HTTP 429 rate_limit: retry later")
    provider.chat_async = AsyncMock()

    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        _run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="start")],
                provider=provider,
                tool_registry=build_default_registry(),
                tool_context=context,
                system_prompt="You are helpful.",
                max_turns=5,
            )
        )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 0
    assert provider.chat_stream_response.call_count == 1
    assert provider.chat_async.await_count == 0


def test_goal_unrecoverable_provider_error_propagates_original_error(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "retry this goal manually",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = ValueError("provider rejected request")
    provider.chat_async = AsyncMock()

    with pytest.raises(ValueError, match="provider rejected request") as raised:
        _run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="start")],
                provider=provider,
                tool_registry=build_default_registry(),
                tool_context=context,
                system_prompt="You are helpful.",
                max_turns=5,
            )
        )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 0
    assert provider.chat_stream_response.call_count == 1
    assert provider.chat_async.await_count == 0
    assert raised.value.aggregate_usage == {  # type: ignore[attr-defined]
        "input_tokens": 0,
        "output_tokens": 0,
    }
    assert raised.value.num_turns == 0  # type: ignore[attr-defined]


def test_goal_max_output_recovery_exhaustion_is_an_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clawcodex_ext.query import query as query_module
    from clawcodex_ext.query.recovery_strategies import (
        RecoveryStrategy,
        _max_output_tokens_exhausted,
    )

    service = make_service(tmp_path)
    service.replace_goal(
        "thread-1",
        "produce the complete response",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    provider.chat.return_value = ChatResponse(
        content="Partial output only.",
        model="test",
        usage={"input_tokens": 2, "output_tokens": 8},
        finish_reason="max_tokens",
        tool_uses=None,
    )
    provider.chat_async = AsyncMock()
    exhausted = RecoveryStrategy(
        name="test_max_output_tokens_exhausted",
        fn=_max_output_tokens_exhausted,
    )
    monkeypatch.setattr(
        query_module,
        "find_recovery_strategies",
        lambda _error_type, state: [
            exhausted
            if state.max_output_tokens_recovery_count >= 3
            else RecoveryStrategy(
                name="force_exhausted_state",
                fn=lambda ctx: (
                    type(ctx.state)(
                        messages=ctx.state.messages,
                        tool_use_context=ctx.state.tool_use_context,
                        max_output_tokens_recovery_count=3,
                        transition=ctx.state.transition,
                    ),
                    [],
                ),
            )
        ],
    )

    with pytest.raises(RuntimeError, match="output token recovery exhausted"):
        _run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="start")],
                provider=provider,
                tool_registry=build_default_registry(),
                tool_context=context,
                system_prompt="You are helpful.",
                max_turns=5,
            )
        )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 0
    assert provider.chat.call_count == 2
    assert provider.chat_async.await_count == 0


def test_replacing_goal_mid_turn_defers_new_goal_evaluation(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    original = service.replace_goal(
        "thread-1",
        "old completion condition",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()
    replacements = []

    def _main_turn(*_args, **_kwargs):
        if not replacements:
            replacements.append(
                service.replace_goal(
                    "thread-1",
                    "new completion condition",
                    completion_mode=GoalCompletionMode.EVALUATOR,
                )
            )
            return ChatResponse(
                content="OLD-TURN-EVIDENCE",
                model="test",
                usage={"input_tokens": 2, "output_tokens": 2},
                finish_reason="end_turn",
                tool_uses=None,
            )
        return ChatResponse(
            content="NEW-TURN-EVIDENCE",
            model="test",
            usage={"input_tokens": 3, "output_tokens": 1},
            finish_reason="end_turn",
            tool_uses=None,
        )

    provider.chat.side_effect = _main_turn
    provider.chat_async = AsyncMock(
        return_value=ChatResponse(
            content='{"met": true, "reason": "new turn completed the new condition"}',
            model="evaluator",
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="end_turn",
        )
    )

    result = _run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="start")],
            provider=provider,
            tool_registry=build_default_registry(),
            tool_context=context,
            system_prompt="You are helpful.",
            max_turns=5,
        )
    )

    goal = service.get_goal("thread-1")
    assert goal is not None
    assert goal.goal_id != original.goal_id
    assert goal.goal_id == replacements[0].goal_id
    assert goal.status is ThreadGoalStatus.COMPLETE
    assert goal.evaluation_count == 1
    assert goal.tokens_used == 6
    assert result.response_text == "NEW-TURN-EVIDENCE"
    assert provider.chat.call_count == 2
    assert provider.chat_async.await_count == 1
    second_main_request = provider.chat.call_args_list[1].args[0]
    assert any(
        OBJECTIVE_UPDATED_STEERING_MARKER in str(message.get("content", ""))
        for message in second_main_request
        if message.get("role") == "user"
    )
    evaluator_request = provider.chat_async.await_args.args[0]
    assert "NEW-TURN-EVIDENCE" in str(evaluator_request)
    assert "OLD-TURN-EVIDENCE" not in str(evaluator_request)


def test_goal_replacement_continuation_respects_explicit_max_turns(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    original = service.replace_goal(
        "thread-1",
        "old completion condition",
        completion_mode=GoalCompletionMode.EVALUATOR,
    )
    context = ToolContext(
        workspace_root=tmp_path,
        session_id="thread-1",
        goal_service=service,
    )
    provider = MagicMock()
    provider.chat_stream_response.side_effect = NotImplementedError()

    def _replace_during_first_turn(*_args, **_kwargs):
        service.replace_goal(
            "thread-1",
            "new completion condition",
            completion_mode=GoalCompletionMode.EVALUATOR,
        )
        return ChatResponse(
            content="Output produced for the old condition.",
            model="test",
            usage={"input_tokens": 2, "output_tokens": 2},
            finish_reason="end_turn",
            tool_uses=None,
        )

    provider.chat.side_effect = _replace_during_first_turn
    provider.chat_async = AsyncMock()

    result = _run(
        run_query_as_agent_loop(
            initial_messages=[UserMessage(content="start")],
            provider=provider,
            tool_registry=build_default_registry(),
            tool_context=context,
            system_prompt="You are helpful.",
            max_turns=1,
        )
    )

    goal = service.get_goal("thread-1")
    assert result.response_text == "[Max tool turns reached]"
    assert result.num_turns == 1
    assert goal is not None
    assert goal.goal_id != original.goal_id
    assert goal.objective == "new completion condition"
    assert goal.status is ThreadGoalStatus.ACTIVE
    assert goal.evaluation_count == 0
    assert provider.chat.call_count == 1
    assert provider.chat_async.await_count == 0
