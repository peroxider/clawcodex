# F-130 TodoWrite Compatibility

## Goal

Preserve legacy `TodoWrite` behavior while allowing LKB to reason about simple todo lists.

## Compatibility Constraints

`TodoWrite` replaces the full todo list and lacks stable task IDs. Because of that, LKB support must be conservative:

- It may validate basic status consistency.
- It may derive aggregate progress.
- It must not promise durable proof chains across turns unless stable IDs are introduced.
- It must preserve the current behavior that all-completed todos clear `context.todos`.

## MVP Rules

- Reject malformed todos before LKB, as today.
- Treat list index as a temporary ID for a single write.
- Deny multiple simultaneous `in_progress` items only if strict logical todo mode is enabled.
- Return `lkb.compatibilityMode: "legacy_todo_write"` when enabled.

## Migration Path

When Task V2 is enabled, prefer `TaskCreate/TaskUpdate`. `TodoWrite` remains for non-interactive/headless compatibility. A future migration can translate `TodoWrite` entries into hidden Task V2 records, but this is not required for MVP.

## Acceptance Criteria

- Existing `TodoWrite` tests pass with LKB disabled.
- With LKB enabled, invalid logical states can be reported without changing the input schema.
- The compatibility adapter never writes to `context.tasks` unless a later migration feature explicitly enables it.

