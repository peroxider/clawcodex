"""GoalService boundary for upstream-compatible thread goals."""

from __future__ import annotations

import threading
from typing import Any

from .files import materialize_goal_objective
from .gate import goal_enabled
from .model import ThreadGoal, ThreadGoalStatus
from .observability import (
    GoalObserver,
    record_goal_cleared,
    record_goal_created,
    record_status_transition,
    record_usage_accounted,
)
from .store import GoalStore, GoalUpdate, current_goal_thread_id

KEEP_TOKEN_BUDGET = object()


class GoalServiceError(RuntimeError):
    """Raised when a goal service operation is invalid or disabled."""


class GoalService:
    """Coordinates goal state mutations behind one service boundary.

    Runtime side effects are intentionally not implemented in Spec 3, but
    command/API callers still route through this class so those effects can be
    added later without giving callers direct store access.
    """

    def __init__(
        self,
        *,
        store: GoalStore | None = None,
        is_enabled: Any = goal_enabled,
        codex_home: Any = None,
        observer: GoalObserver | None = None,
    ) -> None:
        self.store = store if store is not None else GoalStore()
        self._is_enabled = is_enabled
        self.codex_home = codex_home
        self.observer = observer
        self._runtime_lock = threading.RLock()
        self._runtimes: dict[str, Any] = {}

    def register_runtime(self, runtime: Any) -> None:
        thread_id = str(getattr(runtime, "thread_id"))
        with self._runtime_lock:
            self._runtimes[thread_id] = runtime

    def unregister_runtime(self, runtime: Any) -> None:
        thread_id = str(getattr(runtime, "thread_id"))
        with self._runtime_lock:
            if self._runtimes.get(thread_id) is runtime:
                self._runtimes.pop(thread_id, None)

    def get_goal(self, thread_id: str) -> ThreadGoal | None:
        self._ensure_enabled()
        return self.store.get_thread_goal(thread_id)

    def create_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> ThreadGoal:
        """Create a fresh active goal without replacing unfinished work."""
        self._ensure_enabled()
        normalized_objective = self._prepare_objective(objective)
        normalized_budget = _validate_token_budget(token_budget)
        runtime = self._runtime_for_thread(thread_id)
        if runtime is None:
            goal = self.store.insert_thread_goal(
                thread_id,
                normalized_objective,
                ThreadGoalStatus.ACTIVE,
                normalized_budget,
            )
            if goal is None:
                raise _unfinished_goal_error()
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
            return goal

        with runtime.goal_state_permit():
            previous = self.store.get_thread_goal(thread_id)
            if previous is not None and previous.status is not ThreadGoalStatus.COMPLETE:
                raise _unfinished_goal_error()
            runtime.prepare_external_goal_mutation()
            goal = self.store.insert_thread_goal(
                thread_id,
                normalized_objective,
                ThreadGoalStatus.ACTIVE,
                normalized_budget,
            )
            if goal is None:
                raise _unfinished_goal_error()
            runtime.apply_external_goal_set(goal, previous)
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
        return goal

    def set_goal(
        self,
        thread_id: str,
        objective: str | None,
        status: ThreadGoalStatus | str | None = ThreadGoalStatus.ACTIVE,
        token_budget: int | None | object = KEEP_TOKEN_BUDGET,
    ) -> ThreadGoal:
        self._ensure_enabled()
        normalized_objective = self._prepare_objective(objective) if objective is not None else None
        normalized_status = None if status is None else _coerce_status(status)
        normalized_budget = (
            None
            if token_budget is KEEP_TOKEN_BUDGET
            else _normalize_token_budget_update(token_budget)
        )
        runtime = self._runtime_for_thread(thread_id)
        if runtime is not None:
            with runtime.goal_state_permit():
                return self._set_goal_locked(
                    runtime,
                    thread_id,
                    normalized_objective,
                    normalized_status,
                    normalized_budget,
                    token_budget_is_keep=token_budget is KEEP_TOKEN_BUDGET,
                )

        existing = self.store.get_thread_goal(thread_id)

        if existing is None:
            if normalized_objective is None:
                raise GoalServiceError(f"cannot update goal for thread {thread_id}: no goal exists")
            goal = self.store.insert_thread_goal(
                thread_id,
                normalized_objective,
                normalized_status or ThreadGoalStatus.ACTIVE,
                None if token_budget is KEEP_TOKEN_BUDGET else normalized_budget,
            )
            if goal is None:
                raise GoalServiceError(
                    f"cannot create goal for thread {thread_id}: unfinished goal exists"
                )
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
            return goal

        update = (
            GoalUpdate(objective=normalized_objective, status=normalized_status)
            if token_budget is KEEP_TOKEN_BUDGET
            else GoalUpdate(
                objective=normalized_objective,
                status=normalized_status,
                token_budget=normalized_budget,
            )
        )
        goal = self.store.update_thread_goal(
            thread_id,
            update,
            expected_goal_id=existing.goal_id,
        )
        if goal is None:
            raise GoalServiceError(f"cannot update goal for thread {thread_id}")
        record_status_transition(self.observer, existing.status, goal)
        return goal

    def replace_goal(
        self,
        thread_id: str,
        objective: str,
        token_budget: int | None = None,
    ) -> ThreadGoal:
        self._ensure_enabled()
        normalized_objective = self._prepare_objective(objective)
        normalized_budget = _validate_token_budget(token_budget)
        runtime = self._runtime_for_thread(thread_id)
        if runtime is None:
            goal = self.store.replace_thread_goal(
                thread_id,
                normalized_objective,
                ThreadGoalStatus.ACTIVE,
                normalized_budget,
            )
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
            return goal
        with runtime.goal_state_permit():
            previous = self.store.get_thread_goal(thread_id)
            runtime.prepare_external_goal_mutation()
            goal = self.store.replace_thread_goal(
                thread_id,
                normalized_objective,
                ThreadGoalStatus.ACTIVE,
                normalized_budget,
            )
            runtime.apply_external_goal_set(goal, previous)
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
            return goal

    def clear_goal(self, thread_id: str) -> bool:
        self._ensure_enabled()
        runtime = self._runtime_for_thread(thread_id)
        if runtime is None:
            deleted = self.store.delete_thread_goal(thread_id)
            if deleted is not None:
                record_goal_cleared(self.observer, deleted)
            return deleted is not None
        with runtime.goal_state_permit():
            previous = self.store.get_thread_goal(thread_id)
            if previous is None:
                return False
            runtime.prepare_external_goal_mutation()
            deleted = self.store.delete_thread_goal(thread_id)
            if deleted is None:
                return False
            runtime.apply_external_goal_clear(deleted)
            record_goal_cleared(self.observer, deleted)
            return True

    def pause_goal(self, thread_id: str) -> ThreadGoal | None:
        return self.update_goal(thread_id, ThreadGoalStatus.PAUSED)

    def resume_goal(self, thread_id: str) -> ThreadGoal | None:
        return self.update_goal(thread_id, ThreadGoalStatus.ACTIVE)

    def update_goal(
        self,
        thread_id: str,
        status: ThreadGoalStatus | str,
        expected_goal_id: str | None = None,
    ) -> ThreadGoal | None:
        self._ensure_enabled()
        normalized_status = _coerce_status(status)
        runtime = self._runtime_for_thread(thread_id)
        if runtime is None:
            previous = self.store.get_thread_goal(thread_id)
            goal = self.store.update_thread_goal(
                thread_id,
                GoalUpdate(status=normalized_status),
                expected_goal_id=expected_goal_id,
            )
            if goal is not None:
                record_status_transition(
                    self.observer,
                    previous.status if previous is not None else None,
                    goal,
                )
            return goal
        with runtime.goal_state_permit():
            previous = self.store.get_thread_goal(thread_id)
            if previous is None:
                return None
            runtime.prepare_external_goal_mutation()
            goal = self.store.update_thread_goal(
                thread_id,
                GoalUpdate(status=normalized_status),
                expected_goal_id=expected_goal_id,
            )
            if goal is not None:
                runtime.apply_external_goal_set(goal, previous)
                record_status_transition(self.observer, previous.status, goal)
            return goal

    def update_goal_from_runtime(
        self,
        thread_id: str,
        status: ThreadGoalStatus | str,
        expected_goal_id: str | None = None,
    ) -> ThreadGoal | None:
        self._ensure_enabled()
        previous = self.store.get_thread_goal(thread_id)
        goal = self.store.update_thread_goal(
            thread_id,
            GoalUpdate(status=_coerce_status(status)),
            expected_goal_id=expected_goal_id,
        )
        if goal is not None:
            record_status_transition(
                self.observer,
                previous.status if previous is not None else None,
                goal,
            )
        return goal

    def account_usage(
        self,
        thread_id: str,
        expected_goal_id: str | None,
        token_delta: int,
        elapsed_seconds: int,
    ) -> ThreadGoal | None:
        self._ensure_enabled()
        previous = self.store.get_thread_goal(thread_id)
        goal = self.store.account_thread_goal_usage(
            thread_id,
            time_delta=elapsed_seconds,
            token_delta=token_delta,
            expected_goal_id=expected_goal_id,
        )
        if goal is not None:
            record_usage_accounted(
                self.observer,
                goal,
                token_delta=token_delta,
                time_delta_seconds=elapsed_seconds,
            )
            record_status_transition(
                self.observer,
                previous.status if previous is not None else None,
                goal,
            )
        return goal

    def _ensure_enabled(self) -> None:
        if not bool(self._is_enabled()):
            raise GoalServiceError("goals feature is disabled")

    def _runtime_for_thread(self, thread_id: str) -> Any | None:
        with self._runtime_lock:
            return self._runtimes.get(thread_id)

    def _prepare_objective(self, objective: str) -> str:
        return materialize_goal_objective(
            _validate_objective(objective),
            codex_home=self.codex_home,
        ).objective

    def _set_goal_locked(
        self,
        runtime: Any,
        thread_id: str,
        normalized_objective: str | None,
        normalized_status: ThreadGoalStatus | None,
        normalized_budget: int | None,
        *,
        token_budget_is_keep: bool,
    ) -> ThreadGoal:
        existing = self.store.get_thread_goal(thread_id)
        if existing is None:
            if normalized_objective is None:
                raise GoalServiceError(f"cannot update goal for thread {thread_id}: no goal exists")
            runtime.prepare_external_goal_mutation()
            goal = self.store.insert_thread_goal(
                thread_id,
                normalized_objective,
                normalized_status or ThreadGoalStatus.ACTIVE,
                None if token_budget_is_keep else normalized_budget,
            )
            if goal is None:
                raise GoalServiceError(
                    f"cannot create goal for thread {thread_id}: unfinished goal exists"
                )
            runtime.apply_external_goal_set(goal, existing)
            record_goal_created(self.observer, goal)
            record_status_transition(self.observer, None, goal)
            return goal

        update = (
            GoalUpdate(objective=normalized_objective, status=normalized_status)
            if token_budget_is_keep
            else GoalUpdate(
                objective=normalized_objective,
                status=normalized_status,
                token_budget=normalized_budget,
            )
        )
        runtime.prepare_external_goal_mutation()
        goal = self.store.update_thread_goal(
            thread_id,
            update,
            expected_goal_id=existing.goal_id,
        )
        if goal is None:
            raise GoalServiceError(f"cannot update goal for thread {thread_id}")
        runtime.apply_external_goal_set(goal, existing)
        record_status_transition(self.observer, existing.status, goal)
        return goal


def goal_thread_id_from_context(context: Any) -> str:
    explicit = getattr(context, "goal_thread_id", None)
    if explicit:
        return str(explicit)
    tool_context = getattr(context, "tool_context", None)
    session_id = getattr(tool_context, "session_id", None)
    if session_id:
        return str(session_id)
    return current_goal_thread_id()


def _validate_objective(objective: str) -> str:
    text = objective.strip()
    if not text:
        raise GoalServiceError("goal objective cannot be empty")
    return text


def _unfinished_goal_error() -> GoalServiceError:
    return GoalServiceError(
        "cannot create a new goal because this thread has an unfinished "
        "goal; complete the existing goal first, or ask the user to "
        "replace or clear it"
    )


def _coerce_status(status: ThreadGoalStatus | str) -> ThreadGoalStatus:
    if isinstance(status, ThreadGoalStatus):
        return status
    return ThreadGoalStatus.from_wire(str(status))


def _normalize_token_budget_update(value: int | None | object) -> int | None:
    if value is KEEP_TOKEN_BUDGET:
        raise AssertionError("token budget keep sentinel must be handled by caller")
    return _validate_token_budget(value)


def _validate_token_budget(value: int | None | object) -> int | None:
    if value is None:
        return None
    budget = int(value)
    if budget < 0:
        raise GoalServiceError("token budget must be non-negative")
    return budget


__all__ = [
    "KEEP_TOKEN_BUDGET",
    "GoalService",
    "GoalServiceError",
    "goal_thread_id_from_context",
]
