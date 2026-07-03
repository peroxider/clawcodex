"""Equivalent thread-goal API facade for this Python project."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import ThreadGoal, ThreadGoalStatus
from .service import KEEP_TOKEN_BUDGET, GoalService


@dataclass(frozen=True)
class ThreadGoalDTO:
    """API thread-goal shape matching upstream v2 protocol fields."""

    thread_id: str
    objective: str
    status: ThreadGoalStatus
    token_budget: int | None
    tokens_used: int
    time_used_seconds: int
    created_at: int
    updated_at: int

    @classmethod
    def from_model(cls, goal: ThreadGoal) -> "ThreadGoalDTO":
        return cls(
            thread_id=goal.thread_id,
            objective=goal.objective,
            status=goal.status,
            token_budget=goal.token_budget,
            tokens_used=goal.tokens_used,
            time_used_seconds=goal.time_used_seconds,
            created_at=int(goal.created_at.timestamp()),
            updated_at=int(goal.updated_at.timestamp()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "threadId": self.thread_id,
            "objective": self.objective,
            "status": self.status.to_wire(),
            "tokenBudget": self.token_budget,
            "tokensUsed": self.tokens_used,
            "timeUsedSeconds": self.time_used_seconds,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(frozen=True)
class ThreadGoalSetParams:
    thread_id: str
    objective: str | None = None
    status: ThreadGoalStatus | str | None = None
    token_budget: int | None | object = KEEP_TOKEN_BUDGET


@dataclass(frozen=True)
class ThreadGoalSetResponse:
    goal: ThreadGoalDTO


@dataclass(frozen=True)
class ThreadGoalGetParams:
    thread_id: str


@dataclass(frozen=True)
class ThreadGoalGetResponse:
    goal: ThreadGoalDTO | None


@dataclass(frozen=True)
class ThreadGoalClearParams:
    thread_id: str


@dataclass(frozen=True)
class ThreadGoalClearResponse:
    cleared: bool


@dataclass(frozen=True)
class ThreadGoalUpdatedNotification:
    thread_id: str
    turn_id: str | None
    goal: ThreadGoalDTO


@dataclass(frozen=True)
class ThreadGoalClearedNotification:
    thread_id: str


@dataclass(frozen=True)
class GoalProtocolMessage:
    kind: str
    method: str
    payload: object


class GoalEventLog:
    """Small in-process recorder for response/notification ordering tests."""

    def __init__(self) -> None:
        self.messages: list[GoalProtocolMessage] = []

    def response(self, method: str, payload: object) -> None:
        self.messages.append(GoalProtocolMessage("response", method, payload))

    def notification(self, method: str, payload: object) -> None:
        self.messages.append(GoalProtocolMessage("notification", method, payload))

    def clear(self) -> None:
        self.messages.clear()


class ThreadGoalProtocol:
    """Local equivalent of upstream `thread/goal/*` request processors."""

    def __init__(
        self,
        *,
        service: GoalService | None = None,
        events: GoalEventLog | None = None,
    ) -> None:
        self.service = service if service is not None else GoalService()
        self.events = events if events is not None else GoalEventLog()

    def thread_goal_set(self, params: ThreadGoalSetParams) -> ThreadGoalSetResponse:
        goal = self.service.set_goal(
            params.thread_id,
            params.objective,
            status=params.status,
            token_budget=params.token_budget,
        )
        dto = ThreadGoalDTO.from_model(goal)
        response = ThreadGoalSetResponse(goal=dto)
        self.events.response("thread/goal/set", response)
        self.events.notification(
            "thread/goal/updated",
            ThreadGoalUpdatedNotification(
                thread_id=params.thread_id,
                turn_id=None,
                goal=dto,
            ),
        )
        return response

    def thread_goal_get(self, params: ThreadGoalGetParams) -> ThreadGoalGetResponse:
        goal = self.service.get_goal(params.thread_id)
        response = ThreadGoalGetResponse(
            goal=ThreadGoalDTO.from_model(goal) if goal is not None else None
        )
        self.events.response("thread/goal/get", response)
        return response

    def thread_goal_clear(self, params: ThreadGoalClearParams) -> ThreadGoalClearResponse:
        cleared = self.service.clear_goal(params.thread_id)
        response = ThreadGoalClearResponse(cleared=cleared)
        self.events.response("thread/goal/clear", response)
        if cleared:
            self.events.notification(
                "thread/goal/cleared",
                ThreadGoalClearedNotification(thread_id=params.thread_id),
            )
        return response


__all__ = [
    "GoalEventLog",
    "GoalProtocolMessage",
    "ThreadGoalClearParams",
    "ThreadGoalClearResponse",
    "ThreadGoalClearedNotification",
    "ThreadGoalDTO",
    "ThreadGoalGetParams",
    "ThreadGoalGetResponse",
    "ThreadGoalProtocol",
    "ThreadGoalSetParams",
    "ThreadGoalSetResponse",
    "ThreadGoalUpdatedNotification",
]
