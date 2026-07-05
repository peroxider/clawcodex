# F-129 Task V2 Integration

## Goal

Integrate LKB into Task V2 tools: `TaskCreate`, `TaskGet`, `TaskList`, `TaskUpdate`, and `TaskOutput`.

## TaskCreate

Task creation must:

- Normalize input into an LKB `create_task` proposal.
- Create structural facts: `Task(T)`, `Pending(T)`, `Status(T,pending)`.
- Accept optional `metadata.lkb` but validate its shape.
- Return the created task as before plus optional `lkb.createdFacts`.

MVP may allow task creation without solver validation, but it must still emit a validation/audit record when LKB is enabled.

## TaskGet

Task get must optionally expose:

- Derived status: `ready`, `blocked`, `needs_recheck`.
- Active blockers after filtering completed dependencies.
- Last validation run ID.
- Latest denial reason, if any.

This must not obscure the existing `status` field.

## TaskList

Task list must:

- Continue returning summary records.
- Include derived `blockedBy` exactly as existing tests expect.
- Optionally add `lkb` metadata with `derivedStatus`, `blockedReason`, and `nextActions`.
- Sort deterministically.

## TaskUpdate

Task update is the primary gate:

- Field changes can commit without solver when they do not affect logic.
- Status changes must validate.
- Dependency changes must validate cycle and consistency constraints.
- Deletion must validate cascade cleanup.

## TaskOutput

Task output should include LKB metadata for task-list tasks:

- `validation_status`
- `last_validation_run_id`
- `blocked_reason`
- `proof_trace` when requested by a future detail flag

## Acceptance Criteria

- `TaskUpdate({"taskId": B, "status": "in_progress"})` fails when B is blocked by incomplete A.
- Completing A and retrying B succeeds.
- Adding reciprocal dependencies that create a cycle is denied or marked invalid.
- `TaskList` remains compact but can show why a task is unavailable.

