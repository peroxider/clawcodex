"""Compatibility adapters from existing task tools into LKB."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.tool_system.protocol import ToolResult

from .flags import is_logical_kanban_enabled
from .runtime import get_logical_kanban
from .types import ProposedChange


def prepare_todo_write(
    *,
    tool_input: dict[str, Any],
    context: Any,
) -> tuple[ToolResult | None, dict[str, Any] | None]:
    if not is_logical_kanban_enabled():
        return None, None
    change = ProposedChange(kind="legacy_todo_replace_all", payload=dict(tool_input))
    proposal, validation, commit = get_logical_kanban(context).service.run(change, context)
    if commit.committed:
        return None, _accepted_lkb(proposal, validation, commit)
    return _denied_result("TodoWrite", proposal, validation, commit), None


def prepare_task_change(
    *,
    change_kind: str,
    tool_input: dict[str, Any],
    context: Any,
) -> tuple[ToolResult | None, dict[str, Any] | None]:
    if not is_logical_kanban_enabled():
        return None, None
    change = ProposedChange(kind=change_kind, payload=dict(tool_input))  # type: ignore[arg-type]
    runtime = get_logical_kanban(context)
    proposal, validation, commit = runtime.service.run(change, context)
    if commit.committed:
        return None, _accepted_lkb(proposal, validation, commit)
    task_id = tool_input.get("taskId")
    if isinstance(task_id, str) and task_id:
        runtime.latest_denials[task_id] = {
            "validationRunId": validation.validation_id,
            "reason": commit.reason or {"code": "validation_denied"},
            "message": validation.issues[0].message if validation.issues else "Validation denied.",
        }
    return _denied_result("TaskUpdate", proposal, validation, commit), None


def maybe_commit_todo_write(
    *,
    tool_input: dict[str, Any],
    context: Any,
) -> ToolResult | None:
    denied, _lkb = prepare_todo_write(tool_input=tool_input, context=context)
    return denied


def maybe_commit_task_update(
    *,
    tool_input: dict[str, Any],
    context: Any,
) -> ToolResult | None:
    denied, _lkb = prepare_task_change(
        change_kind=_task_update_change_kind(tool_input),
        tool_input=tool_input,
        context=context,
    )
    return denied


def _task_update_change_kind(tool_input: dict[str, Any]) -> str:
    status = tool_input.get("status")
    if status == "deleted":
        return "delete_task"
    if status is not None:
        return "transition_status"
    if tool_input.get("addBlocks") is not None or tool_input.get("addBlockedBy") is not None:
        return "add_dependency"
    return "update_task_fields"


def _accepted_lkb(
    proposal: Any,
    validation: Any,
    commit: Any,
) -> dict[str, Any]:
    return {
        "validationRunId": validation.validation_id,
        "decision": "committed",
        "proposalId": proposal.proposal_id,
        "changeKind": proposal.change.kind,
        "derivedFacts": list(validation.derived_facts),
        "validation": validation.to_dict(),
        "commit": commit.to_dict(),
    }


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
            "lkb": {
                "decision": "denied",
                "validationRunId": validation.validation_id,
                "humanMessage": (
                    validation.issues[0].message if validation.issues else "Validation denied."
                ),
                "proofTrace": list(validation.proof_trace),
                "repairSuggestions": [
                    suggestion.to_dict()
                    for issue in validation.issues
                    for suggestion in issue.repair_suggestions
                ],
            },
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
