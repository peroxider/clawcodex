"""Compatibility adapters from existing task tools into LKB."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.tool_system.protocol import ToolResult

from .flags import is_logical_kanban_enabled
from .runtime import get_logical_kanban
from .types import ProposedChange


def maybe_commit_todo_write(
    *,
    tool_input: dict[str, Any],
    context: Any,
) -> ToolResult | None:
    if not is_logical_kanban_enabled():
        return None
    change = ProposedChange(kind="todo_write", payload=dict(tool_input))
    proposal, validation, commit = get_logical_kanban(context).service.run(change, context)
    if commit.committed:
        return None
    return _denied_result("TodoWrite", proposal, validation, commit)


def maybe_commit_task_update(
    *,
    tool_input: dict[str, Any],
    context: Any,
) -> ToolResult | None:
    if not is_logical_kanban_enabled():
        return None
    change = ProposedChange(kind="task_update", payload=dict(tool_input))
    proposal, validation, commit = get_logical_kanban(context).service.run(change, context)
    if commit.committed:
        return None
    return _denied_result("TaskUpdate", proposal, validation, commit)


def _denied_result(
    tool_name: str,
    proposal: Any,
    validation: Any,
    commit: Any,
) -> ToolResult:
    return ToolResult(
        name=tool_name,
        is_error=True,
        output={
            "success": False,
            "status": "denied",
            "reason": commit.reason or {"code": "validation_denied"},
            "logicalKanban": {
                "proposal": {
                    "proposalId": proposal.proposal_id,
                    "changeKind": proposal.change.kind,
                    "snapshotHash": proposal.snapshot_hash,
                },
                "validation": validation.to_dict(),
                "commit": commit.to_dict(),
            },
        },
    )
