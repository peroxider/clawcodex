# F-143 Runtime LLM Knowledge Facts

## Goal

Allow the agent loop to fill domain knowledge into Logical Kanban **at
runtime**, without requiring the user to pre-populate the predicate
glossary, the rule engine, or any external knowledge base. The agent's
own LLM, web search, local knowledge base, and the model's parametric
knowledge become **fact sources** for the same propose/validate/commit
pipeline that today only accepts hand-written facts and user-supplied
task descriptions.

The non-negotiable invariant: LLM-derived facts **never** replace the
deterministic symbolic gates. They enter the pipeline at the
*fact-extraction* layer (before `Layer1RuleEngine`) or as a
*conservative solver adapter* (F-138-style aggregation), and the audit
log must always make the source of every fact visible so the user can
audit, invalidate, or override them downstream.

This feature is intentionally additive. No existing `TaskUpdate` output
contract changes; no existing `SolverAdapter` is renamed or removed.

## Why this matters

Today's LKB has a hard limit: a transition is committed only when the
six F-132 rules (R-001 … R-006) plus the installed solver adapters
agree, and those rules only know about 17 canonical predicates
(`BUILT_IN_GLOSSARY`). The "50-metre car wash" walkthrough in the
README makes the limit concrete — LKB detects `P-DIST-001` /
`P-SERV-001` ambiguities, but it cannot answer *"should I walk or
drive?"* because the predicate `RequiresVehiclePresence(car,
shop)` is not in the glossary. The user is the only entity allowed to
write that predicate, and a non-technical user typically will not.

F-143 closes the gap by letting the **agent** author those predicates
on the user's behalf, while keeping the **kernel** (rules, solvers,
commit gate) untouched and deterministic.

## Scope

### Three Integration Points

The agent may contribute facts through three concentric layers, ordered
from most-restrictive to most-flexible. Each layer is a separate
`SolverAdapter` or fact pre-processor, registered behind the same
`LKB` feature gate as F-138 Layer 1+.

| Layer | Component | Trust band | Failsafe |
| --- | --- | --- | --- |
| L1: Fact pre-processor | `LlmFactExtractor` (new) | `llm_extracted` 0.50–0.70 | Glossary gate denies unknown predicates |
| L2: Conservative solver | `LlmKnowledgeAdapter` (new) | `llm_extracted` 0.50–0.70 | F-138 "deny by default" aggregation |
| L3: Ambiguity fallback | `AmbiguityDetector._llm_fallback` (new) | `llm_inferred` 0.30–0.50 | Must match a built-in `AmbiguityKind` or be dropped |

The agent picks the layer implicitly by which surface it uses:
- Calling `propose_assertion` with extracted facts → L1.
- Routing a fact through the solver pipeline → L2.
- Letting `AmbiguityDetector` re-classify an un-mapped phrase → L3.

### L1 — Fact Pre-Processor (`LlmFactExtractor`)

A new module `clawcodex_ext/logical_kanban/llm_fact_extractor.py` that
runs **before** `Layer1RuleEngine.evaluate` and **augments**
`FactsSnapshot.facts` with new entries produced by the LLM.

- Input: the natural-language subject/description of the affected task
  (already on `ToolContext.tasks[*]`), the current `FactsSnapshot`, and
  the `BUILT_IN_GLOSSARY`.
- Output: a list of `(CanonicalAssertion, source, confidence)` triples
  that pass `predicate_extractor.validate_assertion`. Any triple whose
  predicate is not in the glossary is dropped with a `lkb_fact_dropped`
  audit event; the agent may re-ask the user to confirm an extension of
  the glossary before retrying.
- Concurrency: synchronous on the commit path when
  `LKB_LLM_FACTS_SYNC=1`; otherwise it runs on the same
  `validate_async` background loop as F-142's ATP enrichment and emits
  the facts as `lkb_fact_extracted` audit events.
- Timeout: bounded by `SolverResourceLimits.timeout_seconds` (default
  30s, F-139) so a slow LLM call cannot stall a `TaskUpdate`.
- Idempotency: extracted facts are keyed on
  `canonical_hash(assertion) + source + model_version`, mirroring the
  F-142 enrichment key.

### L2 — Conservative Solver (`LlmKnowledgeAdapter`)

A new `SolverAdapter` subclass that participates in the existing
`SolverPipeline` and produces **advisory** results. Conservative
aggregation (F-138 §10.7) already handles uncertainty correctly:

- LLM says `pass` → does not flip a symbolic `fail` (aggregation veto
  rule).
- LLM says `fail` → causes the run to become `fail` (conservative
  veto). The resulting `ValidationRun` carries an `error_info.reason =
  "llm_conservative_veto"` so the user can see which adapter
  triggered the flip.
- LLM says `unknown` or times out → no effect, recorded as
  `solver_results[].result='unknown'`.
- The adapter is named `llm-knowledge` and versioned
  `llm-knowledge-v1`. It is registered through
  `solver_adapter.extended_adapters()` next to the F-142 ATP
  adapters, in the order: `layer1 → … → z3 → atp-vampire →
  atp-prover9 → atp-mace4 → llm-knowledge`.
- The adapter is **never the only adapter**; the pipeline remains
  green even when LLM credentials are missing because
  `adapter.available()` returns `False` and the pipeline runs without
  it.

### L3 — Ambiguity Fallback (`AmbiguityDetector._llm_fallback`)

A new private method on the existing `AmbiguityDetector` class, plus
the corresponding entry in `DetectionMethod = Literal[...]`. When
`BUILT_IN_PATTERN_LIBRARY.match(text)` returns no hits, the detector
may call the LLM to:

- Classify the phrase into one of the 9 existing `AmbiguityKind`
  values (must be a literal match — free-form kinds are rejected).
- Produce a tuple of `Interpretation` records whose `code` strings
  come from the pattern library's own `Interpretation.code` enum for
  the matched kind (or, if none, an empty tuple).
- Set `detection_method = "llm_fallback"` on the resulting
  `AmbiguityReport`.

L3 is bounded by:
- a hard cap of 1 LLM call per `detect()` invocation
- a `confidence < 0.30` floor on any LLM-proposed interpretation
  (lower than the existing 0.40 floor on regex-derived
  interpretations, because regex has ground truth)
- a `lkb_llm_fallback_used` metric increment per call

The LLM's output is fed straight into the existing
`WorldGenerator.generate(...)` and the rest of the F-134 pipeline is
unchanged.

### Trust Bands and Source Attribution

`AssumptionSource = Literal["user_input", "default_kb", "inferred",
"user_clarified", "datalog_derived"]` is extended with three new
literal values:

| Source | Default confidence | Invalidatable by | Audit event |
| --- | --- | --- | --- |
| `llm_extracted` | 0.60 | User or LKB causal gate | `lkb_fact_extracted` |
| `web_search` | 0.50 | User or stale-URL check | `lkb_fact_extracted` |
| `agent_inferred` | 0.70 (only when derived from ≥2 other committed facts) | User | `lkb_fact_inferred` |

The `TruthMaintenanceSystem` already supports source-keyed
invalidation; F-143 only adds the three new literals and the
corresponding factory helpers in `audit.py`.

### Audit Event Surface

Three new event types, modeled on the existing `lkb_proof_enrichment`
event from F-137 / F-142:

- `lkb_fact_extracted` — emitted on every successful L1 or L2
  extraction. Payload: `{assertion_hash, source, confidence, model_id,
  glossary_status}`. Idempotency key: `(assertion_hash, source)`.
- `lkb_fact_dropped` — emitted on L1/L2/L3 output that fails the
  glossary gate or the confidence floor. Payload: `{assertion_hash,
  reason, unknown_predicates, model_id}`. Idempotency key:
  `(assertion_hash, reason)`.
- `lkb_llm_fallback_used` — emitted once per L3 call. Payload:
  `{phrase, kind, candidate_count, model_id}`. Idempotency key:
  `(phrase, model_id)`.

All three events go through `append_proof_enrichment_once(...)` so a
retry with the same idempotency key does not double-record.

### LLM Provider Integration

The agent is the **only** LLM caller; LKB does not own provider
credentials. The provider is injected through the existing
`clawcodex_ext.providers.factory.create_provider(...)` factory and
passed in as a constructor argument to `LlmFactExtractor` and
`LlmKnowledgeAdapter`:

```python
extractor = LlmFactExtractor(provider=create_provider("anthropic"))
pipeline = SolverPipeline(adapters=(*default_adapters(),
                                     LlmKnowledgeAdapter(provider=...)))
```

If the provider is `None` (or the factory returns `None` for an
unknown name), all three layers degrade to "feature unavailable":
`LlmFactExtractor.run()` returns `()`, `LlmKnowledgeAdapter.available()`
returns `False`, and `AmbiguityDetector._llm_fallback` is a no-op. The
core commit path is **never** blocked on LLM availability.

### Security Boundary

The F-139 input-sanitisation rules apply unchanged:

- Raw natural-language text from task subjects/descriptions is
  **never** passed verbatim to a solver adapter. The L1 extractor
  routes its output through `encode_solver_literal(...)` before
  re-emitting facts.
- LLM outputs are treated as untrusted: every fact is re-validated
  against the glossary, every confidence value is clamped to
  `[0.0, 1.0]`, and every `Assumption.assumed_value` is run through
  `encode_solver_literal(...)` before being attached to a
  `CanonicalAssertion`.
- The LLM provider's prompt is built from the sanitised snapshot
  (`encode_solver_facts(request)` style), never from the original
  user-controlled strings.

## Requirements

- Add `clawcodex_ext/logical_kanban/llm_fact_extractor.py` exporting
  `LlmFactExtractor` (the L1 component) and a synchronous
  `extract_facts(snapshot, glossary, *, provider=None) -> tuple[CanonicalAssertion, ...]`
  convenience function.
- Add `LlmKnowledgeAdapter` to
  `clawcodex_ext/logical_kanban/solver_adapter.py` (L2). Register it
  in `extended_adapters()` and `default_adapters()` is **not**
  touched (the LLM adapter is opt-in).
- Add `AmbiguityDetector._llm_fallback` and wire it to a public
  `llm_fallback_provider` constructor argument. `None` keeps the
  existing regex-only behaviour.
- Extend `AssumptionSource` in `fuzzy_types.py` with
  `"llm_extracted"`, `"web_search"`, and `"agent_inferred"`.
- Extend `DetectionMethod` in `fuzzy_types.py` is **not** required —
  the literal `"llm_fallback"` is already declared.
- Add three audit-event factories in `audit.py`:
  `event_for_fact_extracted`, `event_for_fact_dropped`,
  `event_for_llm_fallback_used`. Re-use the
  `append_proof_enrichment_once` idempotency machinery.
- Add three metrics counters in `metrics.py`:
  `record_llm_facts_extracted`, `record_llm_facts_dropped`,
  `record_llm_fallback_used`.
- Wire the L1 extractor into `LogicalKanbanService._do_validate`
  **after** `self.snapshot(context)` and **before** the rule engine
  call. When the extractor returns nothing or the provider is `None`,
  the call is a single `if` and the rest of the pipeline is
  unchanged.
- Add a feature flag `LKB_LLM_FACTS` in
  `clawcodex_ext/feature_gate.py` (default off, matching F-141's
  gating pattern). The three layers are unreachable when the flag is
  off; the F-126 master switch still gates everything.
- The default commit path's wall-clock latency (Layer 1 + Layer 2) is
  unchanged when the flag is off or the provider is missing —
  verified by an F-138-style regression test.

## Acceptance Criteria

- A new `tests/logical_kanban/test_f143_llm_facts.py` covers, with a
  stub provider that returns scripted responses:
  - L1 produces `(CanonicalAssertion, ...)` triples whose predicates
    are in the glossary; triples with unknown predicates are
    dropped, and a `lkb_fact_dropped` event is recorded.
  - L1 idempotency: calling `extract_facts` twice with the same
    `(snapshot_hash, model_version)` returns the same set without
    producing duplicate `lkb_fact_extracted` events.
  - L2 `LlmKnowledgeAdapter.solve(request)` returns
    `SolverResponse(result='unknown')` when the provider is `None` or
    the model returns malformed JSON, and `result='fail'` with
    `error_info.reason="llm_conservative_veto"` when the model says
    fail.
  - L2 with the provider missing does not appear in
    `extended_adapters()`; the pipeline runs and the F-138 baseline
    tests stay green.
  - L3 `AmbiguityDetector.detect("50 米开外那儿洗车", ...)` with a
    stub provider returns an `AmbiguityReport` whose
    `detection_method == "llm_fallback"`, whose `kind` is one of the 9
    `AmbiguityKind` literals, and whose `Interpretation.code` values
    are drawn from the same enum set as the regex path.
  - L3 refuses free-form `kind` values; an `AmbiguityKind` mismatch
    raises `ValueError` (or returns an empty ambiguities list) so the
    regex path remains the only producer of new `AmbiguityKind`
    literals.
- `LKB_LLM_FACTS=0` (default) — none of the three layers are
  reachable. The regression test asserts that
  `LlmFactExtractor.run()` is never called, `LlmKnowledgeAdapter` is
  absent from `extended_adapters()`, and `_llm_fallback` is a
  no-op.
- End-to-end: the 50-metre car-wash scenario from the README is
  encoded as a regression test where the LLM stub returns the fact
  `Requires(vehicle, car_shop)`, and the validation result becomes
  `pass` with a non-empty proof trace (no longer
  `divergent_conclusions`).
- All existing `tests/logical_kanban/` tests remain green; no
  existing F-126…F-142 acceptance criterion is weakened.
- Audit log scrubbing: a single `TaskUpdate` that triggers an L1
  extraction produces exactly one `lkb_fact_extracted` event per
  fact, even when the LLM call is retried on transient network
  errors.

## Dependencies

- F-126 — feature gate machinery (`LKB_LLM_FACTS`).
- F-127 — `FactsSnapshot` is the L1 input; the L1 fact pre-processor
  is the inverse of the task-context normaliser.
- F-131 — `BUILT_IN_GLOSSARY` and `validate_assertion` are the
  L1/L2/L3 trust gate.
- F-132 — `Layer1RuleEngine` consumes the augmented snapshot; F-143
  is transparent to the rule engine.
- F-133 — `ValidationRun` and `proposal_id` are the trace-back
  targets.
- F-134 — `WorldGenerator` consumes L3's `AmbiguityReport` unchanged.
- F-136 — `explain.py` already renders `[llm]` annotations; the new
  `llmAnnotations` payload is populated from the L1/L2 events.
- F-137 — three new audit events ride the existing append-log path.
- F-138 — `SolverAdapter` ABC, `SolverPipeline` conservative
  aggregation, and the L1 idempotency key format.
- F-139 — `encode_solver_literal` and `SolverResourceLimits` are the
  security/latency substrate.
- F-142 — async enrichment pattern is reused for the L1 background
  path; `event_for_proof_enrichment` is the template for the three
  new event factories.
- `clawcodex_ext.providers.factory` — the agent's LLM provider
  factory is the single integration point for credentials.

## Out of Scope

- **Glossary mutation by the LLM.** Predicates are never added to
  `BUILT_IN_GLOSSARY` at runtime; the glossary remains a
  human-curated, versioned surface. A future feature can promote
  LLM-proposed predicates into a `user_glossary` overlay, but that is
  a separate concern.
- **Multi-modal fact sources** (image, audio, video). The L1 input
  is text-only.
- **Persistent LLM fact store.** F-137's in-memory session log is
  the only persistence; cross-session fact reuse is left to a
  follow-up feature.
- **Autonomous LLM-generated commit proposals.** F-143 only
  generates **facts**; the proposal/validation/commit orchestration
  remains human- or agent-initiated.
- **Model-specific prompt engineering.** F-143 ships a single
  neutral prompt; provider-specific tuning is left to the
  `extensions/providers_ext` layer.
- **Replacing the F-141 causal gate with an LLM judge.** The
  causal gate is deterministic; F-143 may contribute facts to its
  input but never overrides its verdict.
