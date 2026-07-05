# F-137 Persistence and Audit Events

## Goal

Persist enough LKB state to make validation explainable and reproducible across a session, while keeping the MVP lightweight and local.

## Storage Phases

### Phase 1: In-Memory Plus Context Metadata

- Store current LKB metadata in `ToolContext.tasks[task_id]["metadata"]["lkb"]`.
- Keep validation runs in the LKB runtime for the current session.
- Emit events into existing transcript/tool-result paths where available.

### Phase 2: Session-Local Append Log

- Add `.clawcodex/lkb/<session_id>/events.ndjson` or equivalent user-state path.
- Append proposals, validation runs, commits, denials, and assumption changes.

### Phase 3: Durable Store

- Consider SQLite before PostgreSQL for local agent-loop usage.
- PostgreSQL remains a possible server/deployment backend, not a local MVP dependency.

## Event Types

- `lkb_proposal_created`
- `lkb_validation_run`
- `lkb_commit`
- `lkb_denial`
- `lkb_assumption_invalidated`
- `lkb_revalidation_requested`

## Acceptance Criteria

- A validation run can be inspected after a denied `TaskUpdate`.
- Audit events do not require orchestrator to be running.
- Logs include actor, timestamp, proposal ID, validation run ID, and decision.

