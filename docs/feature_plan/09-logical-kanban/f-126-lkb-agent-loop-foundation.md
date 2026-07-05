# F-126 LKB Agent Loop Foundation

## Goal

Introduce Logical Kanban as a reusable agent-loop capability that enriches todo/task tools with formal state checks, derived blocking, proof traces, and repair guidance.

LKB must not be owned by orchestrator. It lives below orchestrator in the tool system so normal chat sessions, subagents, headless runs, workflows, and orchestrator all get identical task semantics.

## Scope

- Add a new package, proposed as `clawcodex_ext/logical_kanban/`.
- Add a lightweight runtime object to `ToolContext`, for example `logical_kanban`.
- Route task mutations through LKB adapters before committing to `ToolContext.todos` or `ToolContext.tasks`.
- Keep all behavior feature-gated during rollout.
- Preserve existing tool names and model-facing schemas unless a sub-requirement explicitly changes output metadata.

## Non-Goals

- Do not build an orchestrator-specific dashboard first.
- Do not require PostgreSQL, a daemon, or external solver processes for MVP.
- Do not remove `TodoWrite`; support it through a compatibility adapter.

## Interfaces

The foundation exposes an internal service interface:

```python
class LogicalKanbanService:
    def snapshot(self, context: ToolContext) -> FactsSnapshot: ...
    def propose(self, change: ProposedChange, context: ToolContext) -> Proposal: ...
    def validate(self, proposal: Proposal, context: ToolContext) -> ValidationRun: ...
    def commit(self, proposal: Proposal, validation: ValidationRun, context: ToolContext) -> CommitResult: ...
```

The first implementation may combine `propose`, `validate`, and `commit` in a single synchronous helper, but the concepts must remain explicit in the data model.

## Acceptance Criteria

- `ToolContext` can hold an LKB runtime without breaking existing tests that instantiate it directly.
- With the feature flag off, `TodoWrite` and Task V2 behavior remains byte-for-byte compatible where tests assert current outputs.
- With the feature flag on, task status writes are evaluated by LKB before mutating context state.
- Every denied write returns a structured reason and does not mutate task state.
- The service can be used outside orchestrator with only `ToolContext`.

## Dependencies

- F-127 for task normalization.
- F-128 for propose/validate/commit semantics.
- F-132 for the first rule engine.

