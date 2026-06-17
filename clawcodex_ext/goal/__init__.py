"""F-9 `/goal` goal-management subsystem.

A long-running task driver: the user sets an objective via the
``/goal <objective>`` slash command, and the system auto-continues
working on it until completion, token exhaustion, or explicit
pause/clear. Goal state is keyed by ``session_id`` and persisted to
the JSONL transcript as ``{"type": "goal", ...}`` /
``{"type": "goal-cleared", ...}`` entries so ``--resume`` rehydrates
it.

This package provides:

* :class:`GoalState`, :class:`GoalStatus` — the data model
  (see :mod:`clawcodex_ext.goal.types`).
* :func:`state machine transitions <clawcodex_ext.goal.state_machine>`
  — pure functions that return a new ``GoalState``.
* :class:`GoalStateRegistry` — process-wide ``dict[session_id, GoalState]``
  with an RLock so the in-memory state is consistent under
  concurrent reads/writes (see :mod:`clawcodex_ext.goal.registry`).
* :class:`GoalController` — the glue between the REPL turn-completion
  hook, the model-side token usage, the transcript persistence, and
  the in-memory registry (see :mod:`clawcodex_ext.goal.controller`).
* :class:`GoalCommand` — the user-facing ``/goal`` slash command
  (see :mod:`clawcodex_ext.goal.command`).
* :class:`GoalTool` — the model-callable ``get``/``update`` tool
  (see :mod:`clawcodex_ext.goal.tool`).

Reference: ``docs/FEATURE_PLAN.md`` §2.6 (F-9), modelled on upstream
``claude-code-best@3e3e1de81bf89857``.
"""

from __future__ import annotations

from .types import (
    BLOCKED_CONSECUTIVE_THRESHOLD,
    MAX_GOAL_TURNS,
    MAX_OBJECTIVE_CHARS,
    GoalState,
    GoalStatus,
)
from .registry import GoalStateRegistry, get_goal_registry, reset_goal_registry_for_tests
from .state_machine import (
    clear_goal,
    complete_goal,
    compute_active_elapsed_ms,
    continue_from_max_turns,
    increment_turns,
    mark_budget_limited,
    mark_usage_limited,
    pause_goal,
    record_blocker,
    resume_goal,
    set_goal,
    update_tokens,
)

__all__ = [
    "BLOCKED_CONSECUTIVE_THRESHOLD",
    "GoalState",
    "GoalStateRegistry",
    "GoalStatus",
    "MAX_GOAL_TURNS",
    "MAX_OBJECTIVE_CHARS",
    "clear_goal",
    "complete_goal",
    "compute_active_elapsed_ms",
    "continue_from_max_turns",
    "get_goal_registry",
    "increment_turns",
    "mark_budget_limited",
    "mark_usage_limited",
    "pause_goal",
    "record_blocker",
    "reset_goal_registry_for_tests",
    "resume_goal",
    "set_goal",
    "update_tokens",
]
