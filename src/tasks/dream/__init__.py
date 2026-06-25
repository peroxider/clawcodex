"""Facade — src/tasks/dream/__init__.py has been moved to clawcodex_ext.

The full implementation now lives in :mod:`clawcodex_ext.tasks.dream`.
This module re-exports the public surface so existing
``from src.tasks.dream import ...`` call sites keep working without
modification.
"""

from __future__ import annotations

from clawcodex_ext.tasks.dream import (  # noqa: F401
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

__all__ = [
    'DreamTask',
    'DreamTaskState',
    'MAX_DREAM_TURNS',
    'add_dream_turn',
    'complete_dream_task',
    'fail_dream_task',
    'is_dream_task',
    'is_dream_task_terminal',
    'register_dream_task',
    'rollback_dream_lock_after_kill',
]
