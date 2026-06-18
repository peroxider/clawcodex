"""``dream`` task type — F-100.

Mirrors ``typescript/src/tasks/DreamTask/DreamTask.ts`` in shape: a
typed ``DreamTaskState`` dataclass with extension fields plus a
``DreamTask`` adapter registered into the ``RuntimeTaskRegistry``.

The actual spawn / run loop lives in ``clawcodex_ext.dreaming.service``
(Python analog of upstream ``autoDream.ts``); this package only owns
the state machine and the polymorphic ``kill`` dispatch target used
by the chapter-10 ``stop_task`` wiring.
"""

from __future__ import annotations

from src.task_registry import register_task
from src.tasks.dream.dream_task import (
    MAX_DREAM_TURNS,
    DreamTask,
    DreamTaskState,
    add_dream_turn,
    complete_dream_task,
    fail_dream_task,
    is_dream_task,
    is_dream_task_terminal,
    register_dream_task,
    rollback_dream_lock_after_kill,
)

# N1-style centralized registration (mirrors ``src/tasks/__init__.py``).
# Idempotent — re-imports are no-ops.
register_task(DreamTask())

__all__ = [
    "DreamTask",
    "DreamTaskState",
    "MAX_DREAM_TURNS",
    "add_dream_turn",
    "complete_dream_task",
    "fail_dream_task",
    "is_dream_task",
    "is_dream_task_terminal",
    "register_dream_task",
    "rollback_dream_lock_after_kill",
]
