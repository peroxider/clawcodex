# F-136 Explainability and Repair Suggestions

## Goal

Expose LKB decisions in a form that helps the model and user repair the task graph.

## Explanation Sources

Explanations must be generated from:

- facts
- rules
- derived facts
- proof trace
- validation result

Natural language is presentation only. It is not a truth source.

## Repair Suggestion Types

- `complete_prerequisite`
- `remove_dependency`
- `fix_cycle`
- `add_acceptance_proof`
- `clarify_ambiguity`
- `revalidate_task`
- `split_task`

## Tool Output Requirements

Denied tool calls should include:

- short `error`
- `lkb.humanMessage`
- `lkb.proofTrace`
- `lkb.repairSuggestions`

Successful calls may include:

- `lkb.derivedFacts`
- `lkb.nextActions`

## TUI Requirements

The task-list widget can stay compact, but an expanded view should show:

- derived status
- blocked reason
- latest validation result
- proof trace summary

## Acceptance Criteria

- A blocked task explains which prerequisite blocks it.
- A cycle denial lists every task in the cycle.
- A missing acceptance proof denial suggests adding proof or keeping the task in progress.

