# F-133 Validation Runs and Proof Trace

## Goal

Record every LKB validation in a reproducible structure that can be returned to the model, displayed in the TUI, and persisted for audit.

## ValidationRun

```yaml
validation_run_id: V-...
proposal_id: P-...
task_id: T
input_facts_hash: sha256:...
ruleset_hash: sha256:...
engine: layer1-python
engine_version: "0.1"
result: pass | fail | unknown | timeout | error | stale
duration_ms: 12
derived_facts: []
proof_trace: []
counterexample: null
repair_suggestions: []
created_at: ISO-8601
requested_by: agent_id | system
```

## Requirements

- Validation runs are immutable after creation.
- Validation result must be attached to every committed status transition.
- A status transition with no validation run is denied when LKB strict mode is enabled.
- Hashes must include normalized task facts and rules.
- Proof trace must be compact enough for model-facing output and expandable for UI.

## Acceptance Criteria

- Tests can compare validation run hashes for identical snapshots.
- Failed validation includes a human-readable reason and at least one repair suggestion when possible.
- Validation metadata is available in `TaskUpdate` output.

