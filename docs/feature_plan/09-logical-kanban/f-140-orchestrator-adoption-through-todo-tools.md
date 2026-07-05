# F-140 Orchestrator Adoption Through Todo Tools

## Goal

Clarify how orchestrator, workflows, and dashboards use LKB without making LKB orchestrator-specific.

## Principle

Orchestrator consumes LKB by instructing agents to use todo/task tools or by invoking the same tool-layer service. It must not maintain a separate logical kanban state machine that can diverge from agent-loop task state.

## Integration Paths

### Prompt-Level Adoption

Orchestrator prompts ask agents to:

- create Task V2 tasks for issue steps
- mark dependencies
- start tasks only when ready
- include acceptance proof before completion

### Tool-Level Adoption

If orchestrator needs direct automation, it calls the same LKB service used by `TaskUpdate` rather than a private gate.

### Dashboard Adoption

Dashboards read LKB events and task metadata:

- blocked reason
- proof trace summary
- validation run IDs
- stale assumptions

## Acceptance Criteria

- Orchestrator can benefit from LKB without importing solver internals.
- An orchestrator-launched agent and an ordinary user session see the same Task V2 semantics.
- Dashboard work is optional and follows the event contract from F-137.

