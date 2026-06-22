"""Goal data model and constants.

``GoalState`` is the authoritative in-memory shape of a long-running
task. ``GoalStatus`` enumerates the state machine's nodes (see
``docs/FEATURE_PLAN.md`` §2.6.2). The module-level constants fix the
caps that govern auto-continuation, the blocked heuristic, and the
objective length cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# Default cap on how many auto-continuation rounds the controller will
# inject before pausing for the user. Matches the upstream
# ``MAX_GOAL_TURNS = 150`` value (FEATURE_PLAN.md §2.6.3.1).
MAX_GOAL_TURNS: int = 150

# Number of *consecutive* identical blockers before the goal flips to
# ``blocked``. A different blocker reason resets the counter
# (FEATURE_PLAN.md §2.6.3.3).
BLOCKED_CONSECUTIVE_THRESHOLD: int = 3

# Hard cap on the user-supplied objective text length, in characters.
# Longer objectives should be written to a file and referenced by a
# short summary (FEATURE_PLAN.md §2.6.1).
MAX_OBJECTIVE_CHARS: int = 4000


class GoalStatus(str, Enum):
    """Goal state machine nodes.

    The semantics per node are documented in FEATURE_PLAN.md §2.6.2.
    ``str`` mixin lets us serialise to JSON without bespoke adapters
    and compare with raw strings in tests.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    USAGE_LIMITED = "usage_limited"
    MAX_TURNS = "max_turns"
    COMPLETE = "complete"

    @property
    def is_terminal(self) -> bool:
        """``True`` if the state stops further auto-continuation.

        ``max_turns`` is also terminal in the auto-continuation
        sense, but is *not* a true end-state — the user can
        ``/goal continue`` to reset the counter.
        """
        return self in (
            GoalStatus.BLOCKED,
            GoalStatus.BUDGET_LIMITED,
            GoalStatus.USAGE_LIMITED,
            GoalStatus.COMPLETE,
        )


@dataclass
class GoalState:
    """In-memory representation of a single session's goal.

    Mirrors the upstream TS ``GoalState`` interface
    (FEATURE_PLAN.md §2.6.4). All times are epoch milliseconds so
    the dataclass round-trips through JSON without timezone
    surprises. ``accumulated_active_ms`` is the wall time the goal
    has spent in ``active``; pause time is excluded via
    ``compute_active_elapsed_ms`` in :mod:`.state_machine`.
    """

    objective: str
    status: GoalStatus
    token_budget: Optional[int] = None
    tokens_used: int = 0
    start_time_ms: int = 0
    paused_at_ms: Optional[int] = None
    accumulated_active_ms: int = 0
    blocked_attempts: int = 0
    last_block_reason: Optional[str] = None
    created_at_ms: int = 0
    updated_at_ms: int = 0
    turns_executed: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for transcript persistence.

        The ``status`` field is written as its string value so the
        on-disk JSON is human-readable; ``None`` for optional ints
        becomes JSON ``null``.
        """
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoalState":
        """Inverse of :meth:`to_dict`.

        Accepts either the string form ``"active"`` or an existing
        :class:`GoalStatus` member for backwards compatibility with
        code that may have round-tripped an already-decoded object.
        """
        status_raw = payload.get("status", GoalStatus.ACTIVE.value)
        if isinstance(status_raw, GoalStatus):
            status = status_raw
        else:
            status = GoalStatus(str(status_raw))
        return cls(
            objective=str(payload.get("objective", "")),
            status=status,
            token_budget=payload.get("token_budget"),
            tokens_used=int(payload.get("tokens_used", 0) or 0),
            start_time_ms=int(payload.get("start_time_ms", 0) or 0),
            paused_at_ms=payload.get("paused_at_ms"),
            accumulated_active_ms=int(payload.get("accumulated_active_ms", 0) or 0),
            blocked_attempts=int(payload.get("blocked_attempts", 0) or 0),
            last_block_reason=payload.get("last_block_reason"),
            created_at_ms=int(payload.get("created_at_ms", 0) or 0),
            updated_at_ms=int(payload.get("updated_at_ms", 0) or 0),
            turns_executed=int(payload.get("turns_executed", 0) or 0),
        )

    def is_terminal(self) -> bool:
        """``True`` if no further state transitions are valid
        (excluding ``max_turns`` which ``/goal continue`` can recover)."""
        return self.status.is_terminal

    def budget_remaining(self) -> Optional[int]:
        """Tokens left in the budget, or ``None`` when no budget set."""
        if self.token_budget is None:
            return None
        return max(0, int(self.token_budget) - int(self.tokens_used))


__all__ = [
    "BLOCKED_CONSECUTIVE_THRESHOLD",
    "GoalState",
    "GoalStatus",
    "MAX_GOAL_TURNS",
    "MAX_OBJECTIVE_CHARS",
]
