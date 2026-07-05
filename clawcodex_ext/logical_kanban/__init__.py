"""Logical Kanban agent-loop foundation."""

from __future__ import annotations

from .adapters import (
    maybe_commit_task_update,
    maybe_commit_todo_write,
    prepare_task_change,
    prepare_todo_write,
)
from .runtime import LogicalKanbanRuntime, get_logical_kanban
from .service import LogicalKanbanService
from .types import (
    CommitResult,
    FactsSnapshot,
    Proposal,
    ProposedChange,
    RepairSuggestion,
    ValidationIssue,
    ValidationRun,
)

__all__ = [
    "CommitResult",
    "FactsSnapshot",
    "LogicalKanbanRuntime",
    "LogicalKanbanService",
    "Proposal",
    "ProposedChange",
    "RepairSuggestion",
    "ValidationIssue",
    "ValidationRun",
    "get_logical_kanban",
    "maybe_commit_task_update",
    "maybe_commit_todo_write",
    "prepare_task_change",
    "prepare_todo_write",
]
