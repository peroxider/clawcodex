# F-127 Task Context Adapter

## Goal

Define how current ClawCodex todo/task state maps into LKB facts and how validated LKB results map back into `ToolContext`.

## Current State

ClawCodex has two user-facing task surfaces:

- `ToolContext.todos`: legacy `TodoWrite` list with `content`, `status`, and `activeForm`.
- `ToolContext.tasks`: Task V2 records created by `TaskCreate` and changed by `TaskUpdate`.

LKB must treat Task V2 as the canonical structured surface while supporting `TodoWrite` through a lossy compatibility adapter.

## Normalized LKB Task

```yaml
id: string
subject: string
description: string
status: pending | in_progress | completed
owner: string | null
blocks: string[]
blocked_by: string[]
metadata:
  lkb:
    acceptance_proof: string | null
    assertions: string[]
    assumptions: string[]
    validation_run_id: string | null
```

## Fact Mapping

For every Task V2 entry:

```text
Task(T)
Status(T, pending|in_progress|completed)
Pending(T) / Doing(T) / Done(T)
Requires(A, B) for each B.blockedBy includes A
Blocks(A, B) for each A.blocks includes B
Owner(T, owner) when owner exists
HasAcceptanceProof(T) when metadata.lkb.acceptance_proof exists
```

For `TodoWrite` entries:

```text
Task(todo:index)
Status(todo:index, status)
Title(todo:index, content)
```

`TodoWrite` has no stable ID. The adapter must preserve order and use deterministic temporary IDs for one call, but cannot claim long-term proof reproducibility unless the todo has an explicit metadata extension in a later feature.

## Requirements

- Build facts from current context without mutating it.
- Track completed IDs so resolved blockers are excluded from `TaskList` display while still available in proof records.
- Detect dangling blockers and report them as validation warnings.
- Detect cycles in `blockedBy`/`blocks` and deny transitions that depend on cyclic readiness.
- Normalize both `blocks` and `blockedBy` into one dependency graph.

## Acceptance Criteria

- A task with `blockedBy=["A"]` and task A not completed derives `Blocked(task)`.
- A task whose blockers are all completed derives `Ready(task)`.
- If `blocks` and `blockedBy` disagree, LKB emits a consistency warning and can repair by normalizing both directions.
- Existing `TaskList` output can include LKB-derived `blockedBy` without changing required fields.

