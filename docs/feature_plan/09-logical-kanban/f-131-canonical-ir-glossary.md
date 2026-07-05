# F-131 Canonical IR and Glossary

## Goal

Introduce a Canonical Assertion IR as the single source for logical assertions and a glossary that prevents predicate drift.

## Scope

This feature is not required for the first dependency-gating MVP, but it defines the data contract needed for advanced assertions, natural-language rendering, solver compilation, and fuzzy input handling.

## Canonical IR

Minimum shape:

```json
{
  "schema_version": "1.0",
  "role": "axiom",
  "kind": "prerequisite",
  "quantifier": "forall",
  "vars": [{"name": "A", "type": "Task"}, {"name": "B", "type": "Task"}],
  "body": {
    "op": "implies",
    "args": [
      {"pred": "Requires", "args": ["A", "B"]},
      {"pred": "Blocks", "args": ["A", "B"]}
    ]
  }
}
```

## Glossary

The built-in glossary must include:

- `Task`
- `Status`
- `Pending`
- `Ready`
- `Doing`
- `Done`
- `Blocked`
- `Requires`
- `Blocks`
- `CanMoveTo`
- `Permitted`
- `HasAcceptanceProof`
- `Contradicts`
- `Assumes`
- `DerivedFrom`
- `Active`
- `Invalid`

## Requirements

- Every IR predicate must resolve to a glossary entry.
- Unknown predicates put an assertion into `needs_glossary_review`.
- Natural language explanations are rendered from IR/proof trace, not used as truth.
- Compiled solver targets must be reproducible from the IR.
- Hashes must cover canonical JSON, not presentation formatting.

## Acceptance Criteria

- The same IR produces stable hashes across runs.
- Predicate extraction rejects unregistered predicate names.
- Renderer can produce a human-readable explanation for the dependency-blocking rule.
- Future LLM translation is constrained to glossary predicates.

