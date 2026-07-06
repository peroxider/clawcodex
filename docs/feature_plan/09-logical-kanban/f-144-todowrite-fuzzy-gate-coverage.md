# F-144 Legacy Todo Path Fuzzy-Gate Coverage (P0)

## Goal

Make every code path that mutates a user's task surface go through the
F-134 fuzzy-layer commit gate. Today the legacy `TodoWrite` path
returns `result='pass'` and `commit.committed=True` for any
replacement set, regardless of whether individual todo items contain
ambiguities that the multi-world pipeline would have denied. This
defeats the `commit_gate_fuzzy_check` "deny by default" guarantee for
the most common user entry point.

## Background

Reproduced on 2026-07-06 during the F-143 walkthrough. The
reproduction input was a Chinese natural-language task description
with one critical/major ambiguity. With that input:

- `AmbiguityDetector` reports `severity='major'`,
  `needs_clarification=True`.
- `commit_gate_fuzzy_check` denies with
  `fuzzy_assumption_confidence_too_low`.
- `LogicalKanbanService.run(legacy_todo_replace_all, ...)` returns
  `result='pass'` and `commit.committed=True`, with `proofTraceSummary`
  containing only the `LKB-TODOWRITE-COMPAT-ALLOW` rule.

Root cause: `service._validate_legacy_todo_replace_all` short-circuits
to `_accepted(...)` and never consults the F-134 detector, F-134
world generator, or `commit_gate_fuzzy_check`. The same shape of bug
would apply to **any** todo whose `content` field carries an ambiguity
the user expects to be flagged — transportation choices, vendor
selection, scheduling, file-format decisions, deployment-environment
selection, etc. The car-wash reproduction was the simplest case that
exercised the gap; the gap is structural.

## Scope

### Path Coverage

The fix confines itself to the `legacy_todo_replace_all` branch of
`LogicalKanbanService._do_validate`. No change to `TaskUpdate`,
`TaskCreate`, `propose_assertion`, or any of the F-138 solver
adapters. The new code path is:

```
proposal (kind='legacy_todo_replace_all')
   │
   ▼
_validate_legacy_todo_replace_all
   │ for each todo.content:
   │     ambiguity = AmbiguityDetector().detect(content, ...)
   │     record into validation.derived_facts
   │
   ▼
fuzzy_gate = commit_gate_fuzzy_check(worlds, results, ambiguity_report,
                                     is_irreversible=False)
   │ if fuzzy_gate.commit is False:  return denial
   ▼
_accepted(...)
```

### Threshold Mapping

Re-use the existing `FUZZY_THRESHOLD_MINOR` constant and the existing
`Severity` ordering. No new public constants. The denial rule name is
`LKB-TODOWRITE-AMBIG-001`.

### Compatibility Mode Flag

The returned `ValidationRun` carries a new field
`legacy_todo_ambiguities: tuple[dict, ...]` with one entry per todo
whose content triggered a `critical` or `major` ambiguity. Empty tuple
when the gate passes. The field is read by `explain.py` and
`adapters._accepted_lkb` so the legacy path's output matches the
contract that `TaskUpdate` already produces, regardless of which
domain the ambiguity lives in.

## Requirements

- `service._validate_legacy_todo_replace_all` must invoke
  `AmbiguityDetector.detect` on each `todo.content` and aggregate the
  per-todo reports.
- When any per-todo report has `severity in {'critical', 'major'}` and
  `needs_clarification=True`, the run must produce a denial with
  `code='LKB-TODOWRITE-AMBIG-001'` and a repair suggestion that names
  the offending todo `id` and the matching `clarification_prompt`. The
  domain of the offending todo (transportation, vendor, schedule,
  etc.) is opaque to this rule — the gate fires on severity, not on
  the kind of ambiguity.
- When no per-todo report triggers a deny, the run must return
  `result='pass'` exactly as today. The existing
  `LKB-TODOWRITE-COMPAT-ALLOW` proof-step is preserved as the final
  rule in the proof trace.
- The audit log emits a `lkb_legacy_todo_ambiguity` event per denied
  todo, with payload `{todo_id, ambiguity_code, severity,
  clarification_prompt}`. The event factory
  `event_for_legacy_todo_ambiguity` is added to `audit.py`, following
  the `event_for_proof_enrichment` template.
- `_accepted_lkb` in `adapters.py` adds
  `legacyTodoAmbiguities: list[dict]` to the LKB payload when
  non-empty, so the agent loop surface can highlight the offending
  todos in the TUI without re-parsing the proof trace.
- The fuzzy gate is invoked only when the LKB feature flag is on
  (`is_logical_kanban_enabled()`); legacy users with the flag off keep
  the existing fast path.
- Wall-clock impact on a no-ambiguity TodoWrite is bounded to a single
  `AmbiguityDetector.detect` per todo content; a regression test
  asserts < 5 ms total for a 10-todo replacement set on the dev
  reference box, across at least three representative domains
  (transportation, vendor, schedule).

## Acceptance Criteria

- A new `tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py` with
  a stub `AmbiguityDetector` that returns a known `AmbiguityReport`
  asserts:
  - `legacy_todo_replace_all` with one ambiguous todo is denied with
    `code='LKB-TODOWRITE-AMBIG-001'`.
  - `legacy_todo_replace_all` with one ambiguous and nine clean todos
    is denied (single critical/major ambiguity is enough to deny the
    whole batch).
  - `legacy_todo_replace_all` with ten clean todos is committed and
    the proof trace still ends with `LKB-TODOWRITE-COMPAT-ALLOW`.
  - The fixture's `AmbiguityReport` deliberately uses three different
    `AmbiguityKind` values (`semantic_vagueness`, `missing_subject`,
    `acceptance_criteria`) across three test cases, so the gate is
    proven domain-agnostic.
- The end-to-end reproduction input from the bug report, fed through
  `service.run(legacy_todo_replace_all, ...)`, no longer returns
  `commit.committed=True`; it returns a denial whose
  `repair_suggestions[0].message` matches the F-134
  `clarification_prompt` produced by the detector.
- An audit-log replay test asserts that exactly one
  `lkb_legacy_todo_ambiguity` event is emitted per denied todo, and
  zero are emitted on a clean replacement set.
- All existing F-130 tests in `tests/logical_kanban/` remain green;
  in particular `test_audit.py` and `test_orchestrator_adoption.py`
  must continue to pass without modification.

## Dependencies

- F-130 (TodoWrite Compatibility) — provides the legacy path that
  this fix wraps.
- F-134 (Fuzzy Input and Multi-World Handling) — provides
  `AmbiguityDetector`, `WorldGenerator`, `MultiWorldValidator`, and
  `commit_gate_fuzzy_check`.
- F-135 (Assumptions and TMS) — the ambiguous todo is recorded as an
  `Assumption` with `source='user_input'` and `needs_clarification=True`
  so a later user clarification reuses the existing `Clarification`
  machinery.
- F-137 (Persistence and Audit) — new audit event rides the existing
  append-log path.

## Out of Scope

- Changing the `TodoWrite` tool's public schema. The wire format
  stays identical; only the LKB-internal `validation` payload grows a
  new field.
- Per-`TodoWrite` granularity — the gate runs over the **whole
  replacement set** and denies the batch when any single todo is
  ambiguous. Per-todo allowlist is a future feature.
- Migrating legacy todos to `TaskCreate` automatically. Users keep
  the freedom to call `TodoWrite`; they just have to clarify the
  ambiguity when prompted.
- LLM-driven clarification (F-143). F-144 stays deterministic and
  rule-based.
- Adding new `AmbiguityKind` literals or pattern-library entries. F-144
  treats the detector as a black box and only consumes its output.
