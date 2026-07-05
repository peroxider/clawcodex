# F-134 Fuzzy Input and Multi-World Handling

## Goal

Handle ambiguous user/task assertions without letting the model silently choose one interpretation as truth.

## Placement

This is a later-stage feature that builds on Canonical IR. It should be available to task creation and assertion proposal flows, not to every simple status update.

## Ambiguity Types

- lexical ambiguity
- semantic vagueness
- missing subject or object
- unclear dependency direction
- temporal ambiguity
- resource ambiguity
- acceptance-criteria ambiguity
- confidence below threshold

## Multi-World Output

```json
{
  "assertionId": "A",
  "ambiguityReport": {
    "requiresClarification": true,
    "detectedAmbiguities": []
  },
  "worlds": [
    {
      "worldId": "W1",
      "confidence": 0.6,
      "canonicalIr": {},
      "assumptions": []
    }
  ]
}
```

## Commit Policy

- Ambiguous assertions default to deny for irreversible state changes.
- If all worlds produce the same conclusion, the result can be treated as deterministic.
- User clarification overrides inferred assumptions and sets confidence to 1.0 for the clarified field.

## Acceptance Criteria

- Ambiguous dependency direction triggers clarification instead of direct commit.
- Multiple worlds can be validated independently.
- A consistent conclusion across worlds can unblock the task while preserving assumptions in metadata.

