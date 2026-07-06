# F-145 Disambiguating Tokens as Confidence Boosters (P0)

## Goal

Fix a structural anti-pattern in the F-134 pattern library where
**known-disambiguating tokens** were expressed as **matcher
exclusions** (regex negation chains) instead of as **confidence
boosters** on the corresponding `Interpretation`. The bug applies to
every P-XXX pattern that mixes "what to match" with "what to skip
because the user already disambiguated" — not just the
transportation / service-mode pattern that surfaced it.

The fix promotes the anti-pattern to a first-class design: a
`FuzzyPattern` may declare `disambiguating_tokens: tuple[DisambiguatingToken, ...]`
alongside its `interpretations`. Each token is a `(keyword,
interpretation_code, boosted_confidence)` triple that bumps the
matching `Interpretation.base_confidence` while keeping the ambiguity
**visible** to the user.

## Background

Reproduced on 2026-07-06 in the F-143 walkthrough. As an
illustrative (non-shipped) example, a hypothetical `P-PRIORITY-001`
matcher in the built-in library would have been:

```python
matcher=lambda t: "完成" in t
              and "紧急" not in t
              and "普通" not in t
              and "不急" not in t,
```

The substring `"紧急"` in the user's text would cause the entire
pattern to be skipped, so no `Ambiguity` would be recorded. The
detector would return only the unrelated distance / movement
ambiguities. Meanwhile `AmbiguityDetector._refine_interpretations`
already had a refinement that would have pushed `high_priority` to
confidence 0.95 if it had run, but it never ran because the matcher
filtered the input first.

The same anti-pattern exists in the family of `P-XXX` patterns that
mix "match the ambiguous phrase" with "exclude known-resolved
variants" — today the resolution is silently swallowed and the user
never gets asked to confirm the assumption. The priority-mode
reproduction is the simplest case; the same shape of bug would
surface in any domain that builds P-XXX patterns the same way (e.g.
payment-method selection, deployment-environment selection,
file-format selection).

## Scope

### Pattern Schema Extension

`FuzzyPattern` gains a new field:

```python
@dataclass(frozen=True, slots=True)
class DisambiguatingToken:
    keyword: str                       # e.g. "紧急"
    code: str                          # e.g. "high_priority"
    boosted_confidence: float = 0.95   # target confidence when present
    window: int = 16                   # max distance to the ambiguous phrase

@dataclass(frozen=True, slots=True)
class FuzzyPattern:
    pattern_id: str
    category: AmbiguityKind
    severity: Severity
    matcher: Callable[[str], bool]
    interpretations: tuple[Interpretation, ...]
    clarification_prompt: str = ""
    disambiguating_tokens: tuple[DisambiguatingToken, ...] = ()
```

`FuzzyPatternLibrary.add(...)` is updated to round-trip the new
field. The hypothetical `P-PRIORITY-001` is rewritten to use the new
schema instead of the negation chain. **No other built-in pattern is
changed in this feature** — the new mechanism is opt-in per pattern,
and migrating the rest of the built-ins is a follow-up.

### Refinement Pipeline

A new method `AmbiguityDetector._apply_disambiguating_tokens(text,
ambiguity, pattern)` runs **after** `match(...)` returns the pattern
hit. It scans `text` for each `DisambiguatingToken.keyword` within
`window` characters of the matched `phrase`. For each hit:

- The matching `Interpretation.base_confidence` is set to
  `boosted_confidence`.
- The remaining interpretations keep their defaults.
- The hit is recorded in the new `Ambiguity.disambiguating_hits` field
  as a tuple of `(token.keyword, token.code, token.boosted_confidence)`.
- A suffix `"我们已假定为 {code}，请确认。"` is appended to the
  `clarification_prompt` so the user sees both the original question
  and the auto-applied assumption.

The `Ambiguity.severity` and `Ambiguity.resolved` fields are
**unchanged** — `severity` remains `critical` (the user must
confirm) and `resolved` remains `False` (no automatic final
decision).

### World-Generator Compatibility

`WorldGenerator` consumes the (renormalised) interpretation
confidences as it does today. A `disambiguating_hits` tuple with a
single entry whose `boosted_confidence = 0.95` does not change
constraint pruning, but it changes the world-confidence distribution
heavily — the world whose `Assumption.assumed_value` matches the
boosted code dominates. The conservative aggregation
(`commit_gate_fuzzy_check`) still applies, and the `fuzzy_assumption_confidence_too_low`
check still fires when the residual non-boosted world confidences
fall below `FUZZY_THRESHOLD_MINOR`.

## Requirements

- `FuzzyPattern` carries the new `disambiguating_tokens` field with
  copy-on-write semantics. Existing pattern constructions that omit
  the field default to an empty tuple.
- `AmbiguityDetector._apply_disambiguating_tokens` runs after
  `_match_patterns` for every pattern that declares
  `disambiguating_tokens`.
- A hit is recorded on the `Ambiguity` even when the keyword is the
  only thing distinguishing the interpretation. The user must
  always be told which auto-resolved assumption was made.
- The original `P-PRIORITY-001` negation chain is removed. The
  pattern matches whenever the **core** keyword (the regex /
  substring embedded in `matcher`) is present, regardless of
  disambiguating token presence.
- The `Interpretation.base_confidence` values declared in the
  built-in pattern (0.80 / 0.15 / 0.05 for `P-PRIORITY-001` in this
  example) remain the **default** values; the disambiguating-token
  boost is layered on top, then renormalised.
- No change to `AmbiguityReport` schema, `Assumption` schema, or
  `commit_gate_fuzzy_check` aggregation logic.

## Acceptance Criteria

- `tests/logical_kanban/test_f145_disambiguating_tokens.py`:
  - The original three-way split (no disambiguating token) is
    preserved — `detector.detect("完成")` returns the same
    `severity='critical'`, `needs_clarification=True` result as
    today, with three interpretations at 0.80 / 0.15 / 0.05
    (renormalised).
  - Disambiguating-token cases for `P-PRIORITY-001` (`"紧急"`,
    `"普通"`, `"不急"`) each return one `Ambiguity` whose
    `disambiguating_hits` records the matched keyword/code/confidence
    triple and whose `clarification_prompt` ends with the new suffix.
  - The detector is exercised with **at least one non-`P-PRIORITY-001`
    disambiguating-token scenario** built in-test by registering a
    custom `FuzzyPattern` with `disambiguating_tokens` and asserting
    the same boost / hit-recording behaviour. This proves the
    mechanism is reusable beyond `P-PRIORITY-001`.
- `Ambiguity` carries the new `disambiguating_hits` field. The
  `Ambiguity.to_dict()` method serialises it under
  `disambiguatingHits`.
- All existing `test_fuzzy_multiworld.py` tests continue to pass;
  in particular `test_detects_priority_mode_ambiguity` must still
  assert `severity='critical'` and the three interpretations
  continue to be returned.
- The end-to-end reproduction input from the bug report now produces
  a `P-PRIORITY-001` ambiguity in the `AmbiguityReport` (it was
  silently dropped before) and a `disambiguating_hits` entry that
  surfaces `"紧急" → high_priority → 0.95` to the user.

## Dependencies

- F-134 (Fuzzy Input and Multi-World Handling) — the pattern
  library, the detector, the world generator, and the
  `commit_gate_fuzzy_check` aggregation are all touched.
- F-135 (Assumptions and TMS) — `Assumption.assumed_value` continues
  to store the disambiguated code so TMS invalidation works
  unchanged.
- F-137 (Persistence and Audit) — no new audit event, but the
  existing `lkb_proposal` payload grows a
  `disambiguating_hits: list[dict]` field carried from
  `Ambiguity.to_dict()`.

## Out of Scope

- Migrating the other built-in P-XXX patterns
  (`P-DEPDIR-001`, `P-INFO-001`, `P-ACCEPT-001`, etc.) to the new
  `disambiguating_tokens` field. Each is reviewed separately; some
  (e.g. `P-INFO-001`) carry their own negation-chain issues that
  are addressed in F-147, not F-145.
- Auto-resolving the ambiguity to `resolved=True`. F-145 keeps
  resolution human-driven; the suffix is presented as
  *"please confirm"*, never as a silent decision.
- Adding new disambiguating tokens to `P-PRIORITY-001` (e.g.
  `"特急"`, `"加急"`, `"延后"`). The existing three are sufficient
  for the MVP; new tokens are a follow-up that does not need a new
  feature ID.
- Allowing per-tenant / per-session overrides of
  `boosted_confidence`. The value is declared in the pattern
  itself; runtime overrides are a follow-up that depends on
  F-148 (pattern-library flexibility).
