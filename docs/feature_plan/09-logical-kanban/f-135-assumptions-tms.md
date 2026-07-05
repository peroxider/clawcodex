# F-135 Assumptions and Truth Maintenance

## Goal

Track assumptions used by assertions and derived facts, and invalidate dependent task conclusions when assumptions are refuted or clarified.

## Model

```yaml
assumption_id: H-...
field: resource_available
value: true
confidence: 0.85
source: user | agent_inferred | tool_observed | user_clarified
status: active | invalid | superseded
dependent_assertions: []
created_at: ISO-8601
invalidated_at: null
```

## Requirements

- Assertions may reference assumption IDs.
- Derived facts preserve `derived_from` links.
- Invalidating an assumption marks dependent assertions or derived facts as `stale`.
- Stale readiness must surface in `TaskList` and `TaskGet`.
- User clarification can replace an assumption and trigger revalidation.

## MVP

The first implementation may store assumptions in task metadata and perform in-memory propagation for one session.

## Acceptance Criteria

- Invalidating an assumption marks dependent tasks as `needs_recheck`.
- A stale derived fact cannot be used to commit a status transition.
- Revalidation after clarification produces a new validation run.

