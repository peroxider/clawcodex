"""SQLite-backed GoalStore for upstream-compatible thread goals."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import ThreadGoal, ThreadGoalStatus

GOALS_DB_FILENAME = "goals_1.sqlite"

_TOKEN_BUDGET_UNSET = object()


@dataclass(frozen=True)
class GoalUpdate:
    """Partial update for a persisted thread goal.

    ``token_budget`` uses upstream's Option<Option<i64>> shape:
    omitted means no change, ``None`` means clear the budget, and an
    integer means set a new budget.
    """

    objective: str | None = None
    status: ThreadGoalStatus | str | None = None
    token_budget: int | None | object = _TOKEN_BUDGET_UNSET


class GoalStore:
    """Authoritative store for one goal per recoverable thread/session."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else goals_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._bootstrap_schema()

    def close(self) -> None:
        self._conn.close()

    def get_thread_goal(self, thread_id: str) -> ThreadGoal | None:
        row = self._conn.execute(
            """
            SELECT
                thread_id,
                goal_id,
                objective,
                status,
                token_budget,
                tokens_used,
                time_used_seconds,
                created_at_ms,
                updated_at_ms
            FROM thread_goals
            WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchone()
        return _goal_from_row(row) if row is not None else None

    def insert_thread_goal(
        self,
        thread_id: str,
        objective: str,
        status: ThreadGoalStatus | str,
        token_budget: int | None,
    ) -> ThreadGoal | None:
        status = _status_after_budget_limit(_coerce_status(status), 0, token_budget)
        now_ms = _now_ms()
        goal_id = str(uuid.uuid4())

        with self._write_transaction():
            existing = self._conn.execute(
                "SELECT status FROM thread_goals WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if existing is not None and existing["status"] != ThreadGoalStatus.COMPLETE.value:
                return None
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO thread_goals (
                        thread_id,
                        goal_id,
                        objective,
                        status,
                        token_budget,
                        tokens_used,
                        time_used_seconds,
                        created_at_ms,
                        updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                    """,
                    (
                        thread_id,
                        goal_id,
                        objective,
                        status.value,
                        token_budget,
                        now_ms,
                        now_ms,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE thread_goals
                    SET
                        goal_id = ?,
                        objective = ?,
                        status = ?,
                        token_budget = ?,
                        tokens_used = 0,
                        time_used_seconds = 0,
                        created_at_ms = ?,
                        updated_at_ms = ?
                    WHERE thread_id = ?
                    """,
                    (
                        goal_id,
                        objective,
                        status.value,
                        token_budget,
                        now_ms,
                        now_ms,
                        thread_id,
                    ),
                )
            return self.get_thread_goal(thread_id)

    def replace_thread_goal(
        self,
        thread_id: str,
        objective: str,
        status: ThreadGoalStatus | str,
        token_budget: int | None,
    ) -> ThreadGoal:
        status = _status_after_budget_limit(_coerce_status(status), 0, token_budget)
        now_ms = _now_ms()
        goal_id = str(uuid.uuid4())

        with self._write_transaction():
            self._conn.execute(
                """
                INSERT INTO thread_goals (
                    thread_id,
                    goal_id,
                    objective,
                    status,
                    token_budget,
                    tokens_used,
                    time_used_seconds,
                    created_at_ms,
                    updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    goal_id = excluded.goal_id,
                    objective = excluded.objective,
                    status = excluded.status,
                    token_budget = excluded.token_budget,
                    tokens_used = 0,
                    time_used_seconds = 0,
                    created_at_ms = excluded.created_at_ms,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    thread_id,
                    goal_id,
                    objective,
                    status.value,
                    token_budget,
                    now_ms,
                    now_ms,
                ),
            )
            goal = self.get_thread_goal(thread_id)
        if goal is None:
            raise RuntimeError("replace_thread_goal wrote no row")
        return goal

    def update_thread_goal(
        self,
        thread_id: str,
        update: GoalUpdate,
        expected_goal_id: str | None = None,
    ) -> ThreadGoal | None:
        with self._write_transaction():
            goal = self.get_thread_goal(thread_id)
            if goal is None:
                return None
            if expected_goal_id is not None and goal.goal_id != expected_goal_id:
                return None

            if (
                update.objective is None
                and update.status is None
                and update.token_budget is _TOKEN_BUDGET_UNSET
            ):
                return goal

            objective = update.objective if update.objective is not None else goal.objective
            token_budget = (
                goal.token_budget
                if update.token_budget is _TOKEN_BUDGET_UNSET
                else _optional_int(update.token_budget)
            )
            status = _updated_status(goal, update.status, token_budget)
            self._conn.execute(
                """
                UPDATE thread_goals
                SET
                    objective = ?,
                    status = ?,
                    token_budget = ?,
                    updated_at_ms = ?
                WHERE thread_id = ?
                """,
                (objective, status.value, token_budget, _now_ms(), thread_id),
            )
            return self.get_thread_goal(thread_id)

    def delete_thread_goal(self, thread_id: str) -> ThreadGoal | None:
        with self._write_transaction():
            goal = self.get_thread_goal(thread_id)
            if goal is None:
                return None
            self._conn.execute("DELETE FROM thread_goals WHERE thread_id = ?", (thread_id,))
            return goal

    def account_thread_goal_usage(
        self,
        thread_id: str,
        time_delta: int,
        token_delta: int,
        expected_goal_id: str | None = None,
    ) -> ThreadGoal | None:
        time_delta = max(int(time_delta), 0)
        token_delta = max(int(token_delta), 0)
        if time_delta == 0 and token_delta == 0:
            return self.get_thread_goal(thread_id)

        with self._write_transaction():
            goal = self.get_thread_goal(thread_id)
            if goal is None:
                return None
            if expected_goal_id is not None and goal.goal_id != expected_goal_id:
                return None
            if goal.status not in {ThreadGoalStatus.ACTIVE, ThreadGoalStatus.BUDGET_LIMITED}:
                return None

            tokens_used = goal.tokens_used + token_delta
            time_used_seconds = goal.time_used_seconds + time_delta
            status = _status_after_budget_limit(goal.status, tokens_used, goal.token_budget)
            self._conn.execute(
                """
                UPDATE thread_goals
                SET
                    tokens_used = ?,
                    time_used_seconds = ?,
                    status = ?,
                    updated_at_ms = ?
                WHERE thread_id = ?
                """,
                (tokens_used, time_used_seconds, status.value, _now_ms(), thread_id),
            )
            return self.get_thread_goal(thread_id)

    def _bootstrap_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_goals (
                    thread_id TEXT PRIMARY KEY NOT NULL,
                    goal_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'active',
                        'paused',
                        'blocked',
                        'usage_limited',
                        'budget_limited',
                        'complete'
                    )),
                    token_budget INTEGER,
                    tokens_used INTEGER NOT NULL DEFAULT 0,
                    time_used_seconds INTEGER NOT NULL DEFAULT 0,
                    created_at_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )

    def _write_transaction(self) -> "_WriteTransaction":
        return _WriteTransaction(self._conn, self._lock)


class _WriteTransaction:
    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def __enter__(self) -> None:
        self._lock.acquire()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except Exception:
            self._lock.release()
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is None:
                self._conn.execute("COMMIT")
            else:
                self._conn.execute("ROLLBACK")
        finally:
            self._lock.release()


def goals_db_filename() -> str:
    return GOALS_DB_FILENAME


def goals_db_path(*, home: Path | None = None) -> Path:
    if home is not None:
        return home / ".clawcodex" / GOALS_DB_FILENAME
    env_home = os.environ.get("CLAWCODEX_HOME")
    if env_home:
        return Path(env_home) / GOALS_DB_FILENAME
    return Path.home() / ".clawcodex" / GOALS_DB_FILENAME


def current_goal_thread_id() -> str:
    """Return this process's recoverable thread id for goal storage."""
    from src.bootstrap.state import get_session_id

    return str(get_session_id())


def _goal_from_row(row: sqlite3.Row) -> ThreadGoal:
    return ThreadGoal(
        thread_id=str(row["thread_id"]),
        goal_id=str(row["goal_id"]),
        objective=str(row["objective"]),
        status=ThreadGoalStatus.from_wire(str(row["status"])),
        token_budget=_optional_int(row["token_budget"]),
        tokens_used=int(row["tokens_used"]),
        time_used_seconds=int(row["time_used_seconds"]),
        created_at=_datetime_from_ms(int(row["created_at_ms"])),
        updated_at=_datetime_from_ms(int(row["updated_at_ms"])),
    )


def _coerce_status(status: ThreadGoalStatus | str) -> ThreadGoalStatus:
    if isinstance(status, ThreadGoalStatus):
        return status
    return ThreadGoalStatus.from_wire(str(status))


def _updated_status(
    goal: ThreadGoal,
    status: ThreadGoalStatus | str | None,
    token_budget: int | None,
) -> ThreadGoalStatus:
    candidate = goal.status if status is None else _coerce_status(status)
    if goal.status is ThreadGoalStatus.BUDGET_LIMITED and candidate in {
        ThreadGoalStatus.PAUSED,
        ThreadGoalStatus.BLOCKED,
    }:
        return ThreadGoalStatus.BUDGET_LIMITED
    return _status_after_budget_limit(candidate, goal.tokens_used, token_budget)


def _status_after_budget_limit(
    status: ThreadGoalStatus,
    tokens_used: int,
    token_budget: int | None,
) -> ThreadGoalStatus:
    if (
        status is ThreadGoalStatus.ACTIVE
        and token_budget is not None
        and tokens_used >= token_budget
    ):
        return ThreadGoalStatus.BUDGET_LIMITED
    return status


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _datetime_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


__all__ = [
    "GOALS_DB_FILENAME",
    "GoalStore",
    "GoalUpdate",
    "current_goal_thread_id",
    "goals_db_filename",
    "goals_db_path",
]
