from __future__ import annotations

import uuid
from typing import Any

from ..build_tool import Tool, build_tool
from ..context import ToolContext
from ..errors import ToolInputError
from ..protocol import ToolResult
from clawcodex_ext.logical_kanban.context_adapter import task_lkb_view, task_list_view
from clawcodex_ext.logical_kanban import prepare_task_change
from clawcodex_ext.logical_kanban.flags import is_logical_kanban_enabled
from clawcodex_ext.logical_kanban.fuzzy_types import Clarification
from clawcodex_ext.logical_kanban.runtime import get_logical_kanban
from src.utils.task_flags import is_todo_v2_enabled


_TASK_STATUSES = {'pending', 'in_progress', 'completed'}
_LKB_METADATA_FIELDS = {
    'acceptance_proof': str,
    'strict_acceptance': bool,
    'assertions': list,
    'assumptions': list,
    'validation_run_id': str,
    'assumption_clarifications': list,
}


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Auto-mode classifier helpers — mirror TS Task{Create,Get,Update,Output}
# ``toAutoClassifierInput``. The classifier never sees the full task body;
# it sees a compact identity/intent line so any future LLM classifier can
# focus on shape over content.
# ---------------------------------------------------------------------------


def _task_create_classifier_input(input_data: dict) -> str:
    return (input_data or {}).get('subject', '') or ''


def _task_get_classifier_input(input_data: dict) -> str:
    return (input_data or {}).get('taskId', '') or ''


def _task_update_classifier_input(input_data: dict) -> str:
    d = input_data or {}
    parts: list[str] = []
    tid = d.get('taskId')
    if tid:
        parts.append(str(tid))
    status = d.get('status')
    if status:
        parts.append(str(status))
    subject = d.get('subject')
    if subject:
        parts.append(str(subject))
    return ' '.join(parts)


def _task_output_classifier_input(input_data: dict) -> str:
    return (input_data or {}).get('task_id', '') or ''


# ---------------------------------------------------------------------------
# Result formatting helpers (port of TS mapToolResultToToolResultBlockParam)
# ---------------------------------------------------------------------------


def _format_task_created(task_id: str, subject: str) -> str:
    """Format TaskCreate result as human-readable text."""
    return f'Task #{task_id} created successfully: {subject}'


def _format_task_detail(task: dict[str, Any] | None) -> str:
    """Format TaskGet result as human-readable text."""
    if task is None:
        return 'Task not found'
    lines = [
        f'Task #{task["id"]}: {task["subject"]}',
        f'Status: {task["status"]}',
        f'Description: {task["description"]}',
    ]
    blocked_by = task.get('blockedBy') or []
    if blocked_by:
        lines.append(f'Blocked by: {", ".join(f"#{bid}" for bid in blocked_by)}')
    blocks = task.get('blocks') or []
    if blocks:
        lines.append(f'Blocks: {", ".join(f"#{bid}" for bid in blocks)}')
    return '\n'.join(lines)


def _format_task_list(tasks: list[dict[str, Any]]) -> str:
    """Format TaskList result as human-readable text."""
    if not tasks:
        return 'No tasks found'
    lines = []
    for t in tasks:
        owner = f' ({t["owner"]})' if t.get('owner') else ''
        blocked_by = t.get('blockedBy') or []
        blocked = (
            f' [blocked by {", ".join(f"#{bid}" for bid in blocked_by)}]' if blocked_by else ''
        )
        lines.append(f'#{t["id"]} [{t["status"]}] {t["subject"]}{owner}{blocked}')
    return '\n'.join(lines)


def _format_task_updated(
    success: bool,
    task_id: str,
    updated_fields: list[str],
    error: str | None = None,
    status_change: dict[str, str] | None = None,
) -> str:
    """Format TaskUpdate result as human-readable text."""
    if not success:
        return error or f'Task #{task_id} not found'
    return f'Updated task #{task_id} {", ".join(updated_fields)}'


# ---------------------------------------------------------------------------
# Cascade delete helper
# ---------------------------------------------------------------------------


def _cascade_delete(task_id: str, context: ToolContext) -> None:
    """Remove *task_id* from blocks/blockedBy lists of every other task."""
    for other in context.tasks.values():
        blocks = other.get('blocks')
        if blocks and task_id in blocks:
            other['blocks'] = [x for x in blocks if x != task_id]
        blocked_by = other.get('blockedBy')
        if blocked_by and task_id in blocked_by:
            other['blockedBy'] = [x for x in blocked_by if x != task_id]


def _task_update_change_kind(tool_input: dict[str, Any]) -> str:
    status = tool_input.get('status')
    if status == 'deleted':
        return 'delete_task'
    if status is not None:
        return 'transition_status'
    if tool_input.get('addBlocks') is not None or tool_input.get('addBlockedBy') is not None:
        return 'add_dependency'
    return 'update_task_fields'


def _bind_lkb_validation(task: dict[str, Any], lkb: dict[str, Any] | None) -> None:
    if lkb is None:
        return
    validation_run_id = lkb.get('validationRunId')
    if not validation_run_id:
        return
    metadata = dict(task.get('metadata') or {})
    lkb_metadata = dict(metadata.get('lkb') or {})
    lkb_metadata['validation_run_id'] = validation_run_id
    metadata['lkb'] = lkb_metadata
    task['metadata'] = metadata


def _validate_lkb_metadata(metadata: dict[str, Any]) -> None:
    lkb = metadata.get('lkb')
    if lkb is None:
        return
    if not isinstance(lkb, dict):
        raise ToolInputError('metadata.lkb must be an object when provided')
    for key, value in lkb.items():
        expected = _LKB_METADATA_FIELDS.get(key)
        if expected is None:
            raise ToolInputError(f'metadata.lkb.{key} is not a supported LKB metadata field')
        if value is None:
            continue
        if expected is list:
            if key == 'assumption_clarifications':
                if not isinstance(value, list) or not all(
                    isinstance(x, dict) and 'assumption_id' in x and 'action' in x for x in value
                ):
                    raise ToolInputError(
                        'metadata.lkb.assumption_clarifications must be a list of objects '
                        'with assumption_id and action'
                    )
            elif not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise ToolInputError(f'metadata.lkb.{key} must be an array of strings')
        elif not isinstance(value, expected):
            type_name = 'boolean' if expected is bool else 'string'
            raise ToolInputError(f'metadata.lkb.{key} must be a {type_name}')


# ---------------------------------------------------------------------------
# Tool call implementations
# ---------------------------------------------------------------------------


def _task_create_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    subject = tool_input.get('subject')
    description = tool_input.get('description')
    active_form = tool_input.get('activeForm') or ''
    metadata = tool_input.get('metadata') or {}
    if not isinstance(subject, str) or not subject.strip():
        raise ToolInputError('subject must be a non-empty string')
    if not isinstance(description, str) or not description.strip():
        raise ToolInputError('description must be a non-empty string')
    if not isinstance(active_form, str):
        raise ToolInputError('activeForm must be a string when provided')
    if not isinstance(metadata, dict):
        raise ToolInputError('metadata must be an object when provided')
    _validate_lkb_metadata(metadata)

    task_id = _new_task_id()
    denied, lkb = prepare_task_change(
        change_kind='create_task',
        tool_input={
            'taskId': task_id,
            'subject': subject,
            'description': description,
            'activeForm': active_form,
            'metadata': dict(metadata),
        },
        context=context,
    )
    if denied is not None:
        return denied
    context.tasks[task_id] = {
        'id': task_id,
        'subject': subject,
        'description': description,
        'activeForm': active_form,
        'status': 'pending',
        'owner': None,
        'blocks': [],
        'blockedBy': [],
        'metadata': dict(metadata),
        'output': '',
    }
    _bind_lkb_validation(context.tasks[task_id], lkb)
    output: dict[str, Any] = {'task': {'id': task_id, 'subject': subject}}
    if lkb is not None:
        lkb['createdFacts'] = [
            f'Task({task_id})',
            f'Pending({task_id})',
            f'Status({task_id}, pending)',
        ]
        output['lkb'] = lkb
    return ToolResult(
        name='TaskCreate',
        output=output,
    )


TaskCreateTool: Tool = build_tool(
    name='TaskCreate',
    input_schema={
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'subject': {'type': 'string'},
            'description': {'type': 'string'},
            'activeForm': {'type': 'string'},
            'metadata': {'type': 'object'},
        },
        'required': ['subject', 'description'],
    },
    call=_task_create_call,
    prompt="""\
Use this tool to create a structured task list for your current coding session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.
It also helps the user understand the progress of the task and overall progress of their requests.

## When to Use This Tool

Use this tool proactively in these scenarios:

- Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
- Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
- Plan mode - When using plan mode, create a task list to track the work
- User explicitly requests todo list - When the user directly asks you to use the todo list
- User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
- After receiving new instructions - Immediately capture user requirements as tasks
- When you start working on a task - Mark it as in_progress BEFORE beginning work
- After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation

## When NOT to Use This Tool

Skip using this tool when:
- There is only a single, straightforward task
- The task is trivial and tracking it provides no organizational benefit
- The task can be completed in less than 3 trivial steps
- The task is purely conversational or informational

NOTE that you should not use this tool if there is only one trivial task to do. In this case you are better off just doing the task directly.

## Task Fields

- **subject**: A brief, actionable title in imperative form (e.g., "Fix authentication bug in login flow")
- **description**: What needs to be done
- **activeForm** (optional): Present continuous form shown in the spinner when the task is in_progress (e.g., "Fixing authentication bug"). If omitted, the spinner shows the subject instead.

All tasks are created with status `pending`.

## Tips

- Create tasks with clear, specific subjects that describe the outcome
- After creating tasks, use TaskUpdate to set up dependencies (blocks/blockedBy) if needed
- Check TaskList first to avoid creating duplicate tasks
""",
    description='Create a new task in the task list.',
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    is_enabled=is_todo_v2_enabled,
    to_auto_classifier_input=_task_create_classifier_input,
)


def _task_get_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    task_id = tool_input.get('taskId')
    if not isinstance(task_id, str) or not task_id.strip():
        raise ToolInputError('taskId must be a non-empty string')
    task = context.tasks.get(task_id)
    if task is None:
        return ToolResult(name='TaskGet', output={'task': None})
    task_data = {
        'id': task['id'],
        'subject': task['subject'],
        'description': task['description'],
        'status': task['status'],
        'blocks': list(task.get('blocks') or []),
        'blockedBy': list(task.get('blockedBy') or []),
    }
    if is_logical_kanban_enabled():
        task_data['lkb'] = task_lkb_view(context, task_id, include_proof_trace=True)
    return ToolResult(
        name='TaskGet',
        output={'task': task_data},
    )


TaskGetTool: Tool = build_tool(
    name='TaskGet',
    input_schema={
        'type': 'object',
        'additionalProperties': False,
        'properties': {'taskId': {'type': 'string'}},
        'required': ['taskId'],
    },
    call=_task_get_call,
    prompt="""\
Use this tool to retrieve a task by its ID from the task list.

## When to Use This Tool

- When you need the full description and context before starting work on a task
- To understand task dependencies (what it blocks, what blocks it)
- After being assigned a task, to get complete requirements

## Output

Returns full task details:
- **subject**: Task title
- **description**: Detailed requirements and context
- **status**: 'pending', 'in_progress', or 'completed'
- **blocks**: Tasks waiting on this one to complete
- **blockedBy**: Tasks that must complete before this one can start

## Tips

- After fetching a task, verify its blockedBy list is empty before beginning work.
- Use TaskList to see all tasks in summary form.
""",
    description='Get a task by ID from the task list.',
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    is_enabled=is_todo_v2_enabled,
    to_auto_classifier_input=_task_get_classifier_input,
)


def _task_list_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    return ToolResult(
        name='TaskList',
        output={'tasks': task_list_view(context, include_lkb=is_logical_kanban_enabled())},
    )


TaskListTool: Tool = build_tool(
    name='TaskList',
    input_schema={'type': 'object', 'additionalProperties': False, 'properties': {}},
    call=_task_list_call,
    prompt="""\
Use this tool to list all tasks in the task list.

## When to Use This Tool

- To see what tasks are available to work on (status: 'pending', no owner, not blocked)
- To check overall progress on the project
- To find tasks that are blocked and need dependencies resolved
- After completing a task, to check for newly unblocked work or claim the next available task
- **Prefer working on tasks in ID order** (lowest ID first) when multiple tasks are available, as earlier tasks often set up context for later ones

## Output

Returns a summary of each task:
- **id**: Task identifier (use with TaskGet, TaskUpdate)
- **subject**: Brief description of the task
- **status**: 'pending', 'in_progress', or 'completed'
- **owner**: Agent ID if assigned, empty if available
- **blockedBy**: List of open task IDs that must be resolved first (tasks with blockedBy cannot be claimed until dependencies resolve)

Use TaskGet with a specific task ID to view full details including description and comments.
""",
    description='List all tasks in the task list.',
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    is_enabled=is_todo_v2_enabled,
)


def _task_update_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    task_id = tool_input.get('taskId')
    if not isinstance(task_id, str) or not task_id.strip():
        raise ToolInputError('taskId must be a non-empty string')

    updated_fields: list[str] = []
    status_change: dict[str, str] | None = None

    if 'status' in tool_input and tool_input['status'] is not None:
        status = tool_input['status']
        if not isinstance(status, str) or status not in _TASK_STATUSES and status != 'deleted':
            raise ToolInputError(
                'status must be pending|in_progress|completed|deleted when provided'
            )

    for input_key in ('addBlocks', 'addBlockedBy'):
        if input_key in tool_input and tool_input[input_key] is not None:
            ids = tool_input[input_key]
            if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                raise ToolInputError(f'{input_key} must be an array of strings when provided')

    if 'metadata' in tool_input and tool_input['metadata'] is not None:
        md = tool_input['metadata']
        if not isinstance(md, dict):
            raise ToolInputError('metadata must be an object when provided')
        _validate_lkb_metadata(md)

    denied, lkb = prepare_task_change(
        change_kind=_task_update_change_kind(tool_input),
        tool_input=tool_input,
        context=context,
    )
    if denied is not None:
        return denied

    task = context.tasks.get(task_id)
    if task is None:
        out: dict[str, Any] = {
            'success': False,
            'taskId': task_id,
            'updatedFields': [],
            'error': 'Task not found',
        }
        if lkb is not None:
            out['lkb'] = lkb
        return ToolResult(name='TaskUpdate', output=out)

    for field in ('subject', 'description', 'activeForm', 'owner'):
        if field in tool_input and tool_input[field] is not None:
            v = tool_input[field]
            if not isinstance(v, str):
                raise ToolInputError(f'{field} must be a string when provided')
            if v != task.get(field):
                task[field] = v
                updated_fields.append(field)

    if 'status' in tool_input and tool_input['status'] is not None:
        status = tool_input['status']
        if status == 'deleted':
            context.tasks.pop(task_id, None)
            # Cascade delete: remove this task's ID from all other tasks'
            # blocks and blockedBy arrays to prevent dangling references.
            _cascade_delete(task_id, context)
            return ToolResult(
                name='TaskUpdate',
                output={
                    'success': True,
                    'taskId': task_id,
                    'updatedFields': ['deleted'],
                    **({'lkb': lkb} if lkb is not None else {}),
                },
            )
        if status != task.get('status'):
            status_change = {'from': str(task.get('status')), 'to': status}
            task['status'] = status
            _bind_lkb_validation(task, lkb)
            updated_fields.append('status')

    for rel_field, input_key in (('blocks', 'addBlocks'), ('blockedBy', 'addBlockedBy')):
        if input_key in tool_input and tool_input[input_key] is not None:
            ids = tool_input[input_key]
            cur = list(task.get(rel_field) or [])
            for x in ids:
                if x not in cur:
                    cur.append(x)
            if cur != task.get(rel_field):
                task[rel_field] = cur
                updated_fields.append(rel_field)

    if 'metadata' in tool_input and tool_input['metadata'] is not None:
        md = tool_input['metadata']
        existing = dict(task.get('metadata') or {})
        for k, v in md.items():
            if v is None:
                existing.pop(k, None)
            else:
                existing[k] = v
        task['metadata'] = existing
        updated_fields.append('metadata')

    out: dict[str, Any] = {
        'success': True,
        'taskId': task_id,
        'updatedFields': updated_fields,
    }

    # F-135: process assumption clarifications after metadata merge.
    _process_assumption_clarifications(task_id, task, context, out)

    if status_change is not None:
        _bind_lkb_validation(task, lkb)

    if status_change is not None:
        out['statusChange'] = status_change
    if lkb is not None:
        out['lkb'] = lkb
    return ToolResult(name='TaskUpdate', output=out)


def _process_assumption_clarifications(
    task_id: str,
    task: dict[str, Any],
    context: ToolContext,
    out: dict[str, Any],
) -> None:
    """Apply any assumption clarifications stored in task metadata."""
    if not is_logical_kanban_enabled():
        return
    metadata = task.get('metadata')
    if not isinstance(metadata, dict):
        return
    lkb_metadata = metadata.get('lkb')
    if not isinstance(lkb_metadata, dict):
        return
    clarifications = lkb_metadata.get('assumption_clarifications')
    if not isinstance(clarifications, list) or not clarifications:
        return

    runtime = get_logical_kanban(context)
    service = runtime.service
    applied: list[dict[str, Any]] = []
    for raw in clarifications:
        if not isinstance(raw, dict):
            continue
        assumption_id = raw.get('assumption_id')
        action = raw.get('action')
        if not isinstance(assumption_id, str) or not isinstance(action, str):
            continue
        clarification = Clarification(
            assumption_id=assumption_id,
            action=action,
            new_value=raw.get('new_value', ''),
        )
        new_record, old_record, validation_run = service.clarify_assumption(
            context, assumption_id, clarification
        )
        applied.append(
            {
                'assumptionId': new_record.assumption_id,
                'action': action,
                'newValue': new_record.value,
                'validationRunId': validation_run.validation_run_id if validation_run else None,
            }
        )
        if validation_run is not None:
            _bind_lkb_validation(task, {'validationRunId': validation_run.validation_run_id})

    # Clear the clarifications so they are not reprocessed.  _bind_lkb_validation
    # may have replaced the task's lkb dict, so refresh from the task before
    # clearing.
    task_metadata = task.get('metadata')
    if isinstance(task_metadata, dict):
        task_lkb = task_metadata.get('lkb')
        if isinstance(task_lkb, dict):
            task_lkb['assumption_clarifications'] = []
    out['assumptionClarificationsApplied'] = applied


TaskUpdateTool: Tool = build_tool(
    name='TaskUpdate',
    input_schema={
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'taskId': {'type': 'string'},
            'subject': {'type': 'string'},
            'description': {'type': 'string'},
            'activeForm': {'type': 'string'},
            'status': {'type': 'string'},
            'addBlocks': {'type': 'array', 'items': {'type': 'string'}},
            'addBlockedBy': {'type': 'array', 'items': {'type': 'string'}},
            'owner': {'type': 'string'},
            'metadata': {'type': 'object'},
        },
        'required': ['taskId'],
    },
    call=_task_update_call,
    prompt="""\
Use this tool to update a task in the task list.

## When to Use This Tool

**Mark tasks as resolved:**
- When you have completed the work described in a task
- When a task is no longer needed or has been superseded
- IMPORTANT: Always mark your assigned tasks as resolved when you finish them
- After resolving, call TaskList to find your next task

- ONLY mark a task as completed when you have FULLY accomplished it
- If you encounter errors, blockers, or cannot finish, keep the task as in_progress
- When blocked, create a new task describing what needs to be resolved
- Never mark a task as completed if:
  - Tests are failing
  - Implementation is partial
  - You encountered unresolved errors
  - You couldn't find necessary files or dependencies

**Delete tasks:**
- When a task is no longer relevant or was created in error
- Setting status to `deleted` permanently removes the task

**Update task details:**
- When requirements change or become clearer
- When establishing dependencies between tasks

## Fields You Can Update

- **status**: The task status (see Status Workflow below)
- **subject**: Change the task title (imperative form, e.g., "Run tests")
- **description**: Change the task description
- **activeForm**: Present continuous form shown in spinner when in_progress (e.g., "Running tests")
- **owner**: Change the task owner (agent name)
- **metadata**: Merge metadata keys into the task (set a key to null to delete it)
- **addBlocks**: Mark tasks that cannot start until this one completes
- **addBlockedBy**: Mark tasks that must complete before this one can start

## Status Workflow

Status progresses: `pending` -> `in_progress` -> `completed`

Use `deleted` to permanently remove a task.

## Staleness

Make sure to read a task's latest state using `TaskGet` before updating it.

## Examples

Mark task as in progress when starting work:
```json
{"taskId": "1", "status": "in_progress"}
```

Mark task as completed after finishing work:
```json
{"taskId": "1", "status": "completed"}
```

Delete a task:
```json
{"taskId": "1", "status": "deleted"}
```

Claim a task by setting owner:
```json
{"taskId": "1", "owner": "my-name"}
```

Set up task dependencies:
```json
{"taskId": "2", "addBlockedBy": ["1"]}
```
""",
    description='Update a task in the task list.',
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    is_enabled=is_todo_v2_enabled,
    to_auto_classifier_input=_task_update_classifier_input,
)


async def _task_output_call(tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
    """Return the current state / output of a runtime task or todo.

    Chapter-10 / Chunk D / WI-4.1: full polling semantics. ``block``
    defaults to True; when set, the call polls ``runtime_tasks`` until
    the task reaches a terminal state or the ``timeout`` expires.
    Three ``retrieval_status`` values match TS
    ``TaskOutputTool.tsx:52``:

    * ``"success"`` — task is in a terminal state (chapter-10
      ``completed`` / ``failed`` / ``killed``) when polling stops.
      Also returned for non-terminal tasks when ``block=False``-and-
      task-already-terminal (which collapses to the same case).
    * ``"timeout"`` — ``block=True``, deadline expired, task still
      running. The return body still carries the latest snapshot so
      callers see the partial output collected so far.
    * ``"not_ready"`` — ``block=False`` and task is non-terminal.

    The function is ``async def`` so the polling loop can ``await
    asyncio.sleep`` instead of busy-waiting. The dispatch layer (Chunk
    D / WI-4.0) handles sync-vs-async at the registry level — calls
    from sync contexts (test fixtures, tools dispatched from tools)
    still work transparently.
    """
    task_id = tool_input.get('task_id')
    if not isinstance(task_id, str) or not task_id.strip():
        raise ToolInputError('task_id must be a non-empty string')
    task_id = task_id.strip()

    block = bool(tool_input.get('block', True))
    timeout_ms = tool_input.get('timeout')
    if timeout_ms is None:
        timeout_ms = 30_000  # default per TS TaskOutputTool.tsx:33
    try:
        timeout_seconds = float(timeout_ms) / 1000.0
    except (TypeError, ValueError):
        raise ToolInputError('timeout must be a number')

    # Branch 1 — runtime_tasks (chapter-10 source of truth).
    runtime = context.runtime_tasks.get(task_id)
    if runtime is not None:
        if not block:
            return _runtime_task_to_output(task_id, runtime, context)
        return await _poll_runtime_until_terminal(task_id, timeout_seconds, context)

    # Branch 2 — TaskCreate / tasks_v2 todos. Same key space, different
    # semantics; no polling — output text is set or not at the moment
    # of the call.
    task = context.tasks.get(task_id)
    if task is None:
        return ToolResult(name='TaskOutput', output={'retrieval_status': 'success', 'task': None})

    output = str(task.get('output') or '')
    retrieval_status = 'success' if output else 'not_ready'
    task_payload: dict[str, Any] = {
        'task_id': task_id,
        'task_type': 'task_list',
        'status': task.get('status'),
        'description': task.get('description'),
        'output': output,
    }
    if is_logical_kanban_enabled():
        lkb = task_lkb_view(context, task_id, include_proof_trace=True)
        task_payload['lkb'] = {
            'validation_status': lkb['validation_status'],
            'last_validation_run_id': lkb['last_validation_run_id'],
            'blocked_reason': lkb['blockedReason'],
            **(
                {'proof_trace_summary': lkb['proofTraceSummary']}
                if 'proofTraceSummary' in lkb
                else {}
            ),
        }
    return ToolResult(
        name='TaskOutput',
        output={
            'retrieval_status': retrieval_status,
            'task': task_payload,
        },
    )


async def _poll_runtime_until_terminal(
    task_id: str,
    timeout_seconds: float,
    context: ToolContext,
) -> ToolResult:
    """Block until the runtime task is terminal or the deadline expires.

    Returns the same shape ``_runtime_task_to_output`` produces, but
    sets ``retrieval_status="timeout"`` if the deadline expired with
    the task still running. ``await asyncio.sleep`` is bounded at 250ms
    per tick so cancellation is responsive but the loop doesn't burn
    CPU.

    Respects an abort signal on ``context.abort_controller`` if one is
    set: the abort exits the poll early with the current snapshot. The
    parent's stop signal must propagate.
    """
    import asyncio
    import time

    from clawcodex_ext.tasks_core import is_terminal_task_status

    deadline = time.monotonic() + timeout_seconds
    poll_interval = 0.25
    while True:
        runtime = context.runtime_tasks.get(task_id)
        if runtime is None:
            # Task evicted mid-poll — treat as success/None like the
            # not-found branch above.
            return ToolResult(
                name='TaskOutput',
                output={'retrieval_status': 'success', 'task': None},
            )
        if is_terminal_task_status(runtime.status):
            return _runtime_task_to_output(task_id, runtime, context)

        # Abort fast-path — if the parent's controller is signalled,
        # exit with the current snapshot rather than waiting out the
        # remaining timeout. ``abort_controller`` is non-optional on
        # ``ToolContext`` so the historical truthiness/getattr indirection
        # is gone.
        if context.abort_controller.signal.aborted:
            return _runtime_task_to_output(task_id, runtime, context)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # Timed out — return the running snapshot but flag it.
            snapshot = _runtime_task_to_output(task_id, runtime, context)
            timed_out = dict(snapshot.output) if isinstance(snapshot.output, dict) else {}
            timed_out['retrieval_status'] = 'timeout'
            return ToolResult(name='TaskOutput', output=timed_out)
        await asyncio.sleep(min(poll_interval, max(remaining, 0.01)))


def _runtime_task_to_output(
    task_id: str,
    runtime: Any,
    context: ToolContext,
) -> ToolResult:
    """Project a ``runtime_tasks`` entry into the model-facing output shape."""
    # Local imports defer the cycle.
    from src.tasks.local_agent import LocalAgentTaskState
    from src.tasks.local_shell import LocalShellTaskState
    from clawcodex_ext.tasks_core import is_terminal_task_status

    if isinstance(runtime, LocalShellTaskState):
        # Reuse the existing rich snapshot helper (combined output capture,
        # exit-code marker stripping, etc.) so behavior is unchanged.
        from src.tool_system.tools.bash.background import read_background_output

        snapshot = read_background_output(context, task_id)
        if snapshot is None:
            return ToolResult(
                name='TaskOutput',
                output={'retrieval_status': 'success', 'task': None},
            )
        return ToolResult(
            name='TaskOutput',
            output={
                'retrieval_status': 'success',
                'task': {
                    'task_id': task_id,
                    'task_type': 'bash_background',
                    'status': snapshot['status'],
                    'exit_code': snapshot['exit_code'],
                    'command': snapshot['command'],
                    'description': snapshot['description'],
                    'output': snapshot['output'],
                    'truncated': snapshot['truncated'],
                    'pid': snapshot['pid'],
                    'started_at': snapshot['started_at'],
                    'finished_at': snapshot['finished_at'],
                },
            },
        )

    if isinstance(runtime, LocalAgentTaskState):
        text = runtime.result_text or ''
        if is_terminal_task_status(runtime.status):
            retrieval_status = 'success'
        else:
            retrieval_status = 'not_ready'
        return ToolResult(
            name='TaskOutput',
            output={
                'retrieval_status': retrieval_status,
                'task': {
                    'task_id': task_id,
                    'task_type': 'local_agent',
                    'status': runtime.status,
                    'description': runtime.description,
                    'agent_type': runtime.agent_type,
                    'output': text,
                },
            },
        )

    # Unknown TaskStateBase subclass — surface what we have. Future task
    # types can extend this dispatch without touching the readers above.
    return ToolResult(
        name='TaskOutput',
        output={
            'retrieval_status': 'success',
            'task': {
                'task_id': task_id,
                'task_type': runtime.type,
                'status': runtime.status,
                'description': runtime.description,
                'output': '',
            },
        },
    )


TaskOutputTool: Tool = build_tool(
    name='TaskOutput',
    input_schema={
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'task_id': {'type': 'string'},
            'block': {
                'type': 'boolean',
                'default': True,
                'description': 'Whether to wait for task completion (default: true)',
            },
            # Chapter-10 / WI-4.1 schema bounds (mirrors TS
            # TaskOutputTool.tsx:33 ``z.number().min(0).max(600000)``).
            'timeout': {
                'type': 'number',
                'minimum': 0,
                'maximum': 600000,
                'default': 30000,
                'description': 'Max wait time in ms (default 30000; max 600000)',
            },
        },
        'required': ['task_id'],
    },
    call=_task_output_call,
    prompt="""\
Get the output of a running or completed background task.

- Takes a task_id parameter identifying the task to get output for
- Returns the task status and any available output
- Use this tool to check on the progress or results of background tasks
""",
    description='Get output for a background task.',
    aliases=('AgentOutputTool', 'BashOutputTool'),
    strict=True,
    max_result_size_chars=100_000,
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    to_auto_classifier_input=_task_output_classifier_input,
)
