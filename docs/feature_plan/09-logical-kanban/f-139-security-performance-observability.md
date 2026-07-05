# F-139 Security Performance Observability

## Goal

Capture non-functional requirements for the agent-loop LKB implementation.

## Correctness

- Solver `fail`, `unknown`, `timeout`, or `error` denies strict commits.
- Status exclusivity is always maintained.
- Commit requires a current validation run for status transitions.
- Natural language explanation never overrides formal result.

## Security

- Agent writes pass through tool APIs only.
- No external solver process receives unsanitized text.
- External solver execution must have timeout and resource limits.
- Human override, when added, must be explicit and audited.

## Performance

- Layer 1 validation for 1,000 tasks under 200ms.
- Task update overhead under 50ms for common small task lists.
- Fact snapshot under 100ms.
- Cache hashes for repeated TaskList calls when context has not changed.

## Observability

Metrics to expose later:

- validation count by result
- denial count by rule
- average validation duration
- blocked task count
- stale assumption count
- solver timeout count

## Acceptance Criteria

- LKB failure cannot corrupt `ToolContext.tasks`.
- Performance tests cover 1,000 task dependency graph.
- Denial reasons are machine-readable and human-readable.

