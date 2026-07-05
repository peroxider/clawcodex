# F-128 Propose Validate Commit Tool Contract

## Goal

Make every todo/task mutation follow a logical three-step contract: propose, validate, commit. This implements the source spec's "Agent can propose, not directly commit" rule at the tool-call boundary.

## Contract

```text
tool input
  -> ProposedChange
  -> ValidationRun
  -> CommitResult
  -> ToolResult
```

The tool implementation may execute this synchronously, but it must not update `ToolContext` before validation has produced an allow result.

## ProposedChange Types

- `create_task`
- `update_task_fields`
- `transition_status`
- `delete_task`
- `add_dependency`
- `remove_dependency`
- `legacy_todo_replace_all`

## Commit Rules

- `pending -> in_progress` requires the task to be ready and not blocked.
- `in_progress -> completed` requires acceptance proof when strict mode is enabled.
- `completed -> pending` is allowed only as an explicit reopen and must be audited.
- `deleted` must cascade dependency cleanup only after validation.
- Unknown, timeout, or error results deny commit unless a future human override path is active.

## Model-Facing Output

Successful updates keep existing fields and add optional LKB metadata:

```json
{
  "success": true,
  "taskId": "T",
  "updatedFields": ["status"],
  "lkb": {
    "validationRunId": "V-...",
    "decision": "committed",
    "derivedFacts": ["Ready(T)", "CanMoveTo(T,in_progress)"]
  }
}
```

Denied updates:

```json
{
  "success": false,
  "taskId": "T",
  "updatedFields": [],
  "error": "blocked_task_cannot_enter_in_progress",
  "lkb": {
    "decision": "denied",
    "validationRunId": "V-...",
    "humanMessage": "Task T cannot start because prerequisite A is still pending.",
    "proofTrace": [],
    "repairSuggestions": []
  }
}
```

## Acceptance Criteria

- A denied transition does not mutate `context.tasks`.
- Tool outputs remain useful to the model without requiring a separate API call.
- A validation run ID is present for every status transition when LKB is enabled.
- Unit tests can assert proposed, denied, and committed paths without launching orchestrator.

