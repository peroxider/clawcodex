# F-132 Layer-1 Rule Engine

## Goal

Ship a fast in-process rule engine that covers the highest-value LKB checks without requiring external solvers.

## MVP Rules

```text
R-001: Requires(A,B) and not Done(A) and not Done(B) -> Blocked(B)
R-002: Blocked(T) -> not CanMoveTo(T,in_progress)
R-003: not Blocked(T) and Status(T,pending) -> Ready(T)
R-004: Ready(T) -> CanMoveTo(T,in_progress)
R-005: Done(T) requires HasAcceptanceProof(T) when strict acceptance is enabled
R-006: Dependency cycles invalidate readiness for all tasks in the cycle
```

## Engine Requirements

- Build a facts snapshot from `ToolContext`.
- Derive facts deterministically.
- Return proof traces for every denial.
- Run synchronously inside tool calls.
- Handle at least 1,000 task records in under 200ms on a typical development machine.

## Output

```json
{
  "result": "pass",
  "derivedFacts": ["Ready(B)", "CanMoveTo(B,in_progress)"],
  "proofTrace": []
}
```

or:

```json
{
  "result": "fail",
  "violatedRule": "R-002",
  "derivedFacts": ["Blocked(B)", "NotCanMoveTo(B,in_progress)"],
  "proofTrace": [
    {
      "rule": "R-001",
      "premises": ["Requires(A,B)", "NotDone(A)"],
      "conclusion": "Blocked(B)"
    }
  ]
}
```

## Acceptance Criteria

- Rule output is deterministic for identical snapshots.
- Rule traces reference rule IDs, premises, and conclusions.
- Cycles are reported with involved task IDs.
- Completed blockers no longer block dependent tasks.

