"""Compatibility adapters from existing task tools into LKB."""

from __future__ import annotations

from typing import Any

from clawcodex_ext.tool_system.protocol import ToolResult

from .audit import get_audit_log
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
    change = ProposedChange(kind='legacy_todo_replace_all', payload=dict(tool_input))
    proposal, validation, commit = get_logical_kanban(context).service.run(change, context)
    if commit.committed:
        return None, _accepted_lkb(proposal, validation, commit)
    return _denied_result('TodoWrite', proposal, validation, commit), None


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
    task_id = tool_input.get('taskId')
    if isinstance(task_id, str) and task_id:
        runtime.latest_denials[task_id] = {
            'validationRunId': validation.validation_id,
            'proposalId': proposal.proposal_id,
            'reason': commit.reason or {'code': 'validation_denied'},
            'message': validation.issues[0].message if validation.issues else 'Validation denied.',
            'result': validation.result,
            'proofTrace': list(validation.proof_trace),
            'repairSuggestions': [
                suggestion.to_dict()
                for issue in validation.issues
                for suggestion in issue.repair_suggestions
            ],
            'timestamp': validation.created_at,
        }
    return _denied_result('TaskUpdate', proposal, validation, commit), None


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
    status = tool_input.get('status')
    if status == 'deleted':
        return 'delete_task'
    if status is not None:
        return 'transition_status'
    if tool_input.get('addBlocks') is not None or tool_input.get('addBlockedBy') is not None:
        return 'add_dependency'
    return 'update_task_fields'


def _accepted_lkb(
    proposal: Any,
    validation: Any,
    commit: Any,
) -> dict[str, Any]:
    out = {
        'validationRunId': validation.validation_run_id,
        'proposalId': validation.proposal_id,
        'taskId': validation.task_id,
        'decision': 'committed',
        'result': validation.result,
        'engine': validation.engine,
        'engineVersion': validation.engine_version,
        'inputFactsHash': validation.input_facts_hash,
        'rulesetHash': validation.ruleset_hash,
        'durationMs': validation.duration_ms,
        'changeKind': proposal.change.kind,
        'derivedFacts': list(validation.derived_facts),
        'proofTrace': list(validation.proof_trace),
        'nextActions': _next_actions_for_accepted(proposal, validation),
        'validation': validation.to_dict(),
        'commit': commit.to_dict(),
    }
    if proposal.change.kind == 'legacy_todo_replace_all':
        out['compatibilityMode'] = 'legacy_todo_write'
        out['progress'] = _legacy_todo_progress(proposal.change.payload)
        if validation.legacy_todo_ambiguities:
            out['legacyTodoAmbiguities'] = list(validation.legacy_todo_ambiguities)
    return out


def _denied_result(
    tool_name: str,
    proposal: Any,
    validation: Any,
    commit: Any,
) -> ToolResult:
    lkb_payload: dict[str, Any] = {
        'decision': 'denied',
        'validationRunId': validation.validation_run_id,
        'proposalId': validation.proposal_id,
        'taskId': validation.task_id,
        'result': validation.result,
        'engine': validation.engine,
        'engineVersion': validation.engine_version,
        'inputFactsHash': validation.input_facts_hash,
        'rulesetHash': validation.ruleset_hash,
        'durationMs': validation.duration_ms,
        'humanMessage': (
            validation.issues[0].message if validation.issues else 'Validation denied.'
        ),
        'proofTrace': list(validation.proof_trace),
        'counterexample': validation.counterexample,
        'repairSuggestions': [
            suggestion.to_dict()
            for issue in validation.issues
            for suggestion in issue.repair_suggestions
        ],
        'validation': validation.to_dict(),
    }
    if proposal.change.kind == 'legacy_todo_replace_all':
        lkb_payload['compatibilityMode'] = 'legacy_todo_write'
        lkb_payload['progress'] = _legacy_todo_progress(proposal.change.payload)
        if validation.legacy_todo_ambiguities:
            lkb_payload['legacyTodoAmbiguities'] = list(validation.legacy_todo_ambiguities)
    return ToolResult(
        name=tool_name,
        is_error=True,
        output={
            'success': False,
            'status': 'denied',
            'reason': commit.reason or {'code': 'validation_denied'},
            'lkb': lkb_payload,
            'logicalKanban': {
                'proposal': {
                    'proposalId': proposal.proposal_id,
                    'changeKind': proposal.change.kind,
                    'snapshotHash': proposal.snapshot_hash,
                },
                'validation': validation.to_dict(),
                'commit': commit.to_dict(),
            },
        },
    )


def _next_actions_for_accepted(proposal: Any, validation: Any) -> list[str]:
    """Derive a short list of next actions for an accepted change."""
    kind = proposal.change.kind
    payload = proposal.change.payload
    if kind == 'transition_status':
        status = payload.get('status') if isinstance(payload, dict) else None
        if status == 'in_progress':
            return ['complete_task']
        if status == 'completed':
            return []
        if status == 'pending':
            return ['start_task']
    if kind == 'create_task':
        return ['start_task']
    if kind in {'add_dependency', 'remove_dependency'}:
        return ['revalidate_task']
    return []


def _legacy_todo_progress(payload: dict[str, Any]) -> dict[str, int]:
    counts = {'total': 0, 'pending': 0, 'in_progress': 0, 'completed': 0}
    todos = payload.get('todos')
    if not isinstance(todos, list):
        return counts
    counts['total'] = len(todos)
    for todo in todos:
        if isinstance(todo, dict) and todo.get('status') in counts:
            counts[str(todo['status'])] += 1
    return counts
