# F-141 Causal Verification Layer (CAP-compatible)

## Goal

Add an in-process causal verification gate that mirrors the Causal Agent
Protocol (CAP) verb semantics — without depending on the upstream
`cap-example` reference repository (0 stars, teaching-only). The layer
sits *after* the symbolic gates from F-132 / F-138 and answers a
narrower question than structural validation: **does a proposed
dependency edge reflect a real causal mechanism, and how strong is
that mechanism?**

Causal verification never blocks a commit on its own. It augments the
symbolic proof trace with a `causal_weight` value and an
`is_significant` flag that the TUI, the orchestrator dashboard, and the
human override workflow can use.

## Scope

### CAP Verb Surface

Reuse the three CAP verbs from the spec (`graph.neighbors`,
`intervene.do`, `observe.predict`) but expose them as an in-process
Python API rather than an HTTP service. The HTTP shape from §10.6 is
retained as the audit-log wire format, so the eventual move to a real
CAP-compatible daemon is a transport swap only.

| Verb | Input | Output |
| --- | --- | --- |
| `meta.capabilities` | — | `{verbs: [graph.neighbors, intervene.do, observe.predict]}` |
| `graph.neighbors` | `{node, scope ∈ {parents, children, ancestors, descendants}}` | `{neighbors: [task_id, …]}` |
| `intervene.do` | `{treatment_node, treatment_value, outcome_node}` | `{causal_effect, is_significant, mechanism}` |
| `observe.predict` | `{node}` | `{baseline: {value, confidence}}` |

### Causal Weight

`causal_weight` is the normalised intervention effect:

```
causal_weight = | E[Y | do(T=1)] - E[Y | do(T=0)] | / max_observable_effect
```

Thresholds (mirroring spec §10.6):

| Range | Tag | Effect on commit |
| --- | --- | --- |
| `≥ 0.7` | `significant` | Edge treated as causally supported; recorded on the validation run |
| `0.4 – 0.7` | `moderate` | Edge accepted structurally; surfaced as "needs human review" in audit UI |
| `< 0.4` | `weak` | Edge rejected as "not causal"; user must supply an override reason |

### In-Process Synthetic Graph

Per spec §10.6 the implementation is a **lightweight synthetic graph**,
not a learned SCM:

1. Build a `CausalGraph` from the same `FactsSnapshot` that drives F-132.
2. Seed `Causes` edges from three sources, in priority order:
   - `metadata.lkb.causes` declarations on the source task (manual labels).
   - `metadata.lkb.acceptance_proof` references that touch the target task
     (proof-driven edges).
   - Layer-1 `Requires` edges as a weak default (`causal_weight = 0.5`,
     mechanism = `structural`).
3. `intervene.do` is computed by re-running the structural solver with the
   treatment forced on/off, then dividing the observable delta by the
   maximum observed delta in the snapshot. No Pearl-style identifiability
   machinery is required for this MVP.

### Dual-Layer Gate Order

Follow the spec's "symbolic first, causal second" fast-fail order:

```
agent proposes dependency edge
   │
   ▼
Symbolic gate (F-132 / F-138 Layer 1–4)  ← fast, deterministic
   │ pass
   ▼
Causal gate (this feature, Layer 5')
   │ pass or warn
   ▼
commit + audit record (causal_weight, mechanism)
```

The causal gate always runs after the symbolic gate, but its outcomes
are advisory when `LKB_STRICT_CAUSAL` is unset and binding when it is.
The pipeline's conservative aggregation from F-138 still wins: any
symbolic fail stays fail regardless of causal weight.

## Requirements

- Expose the CAP verb surface as a pure-Python module
  (`clawcodex_ext/logical_kanban/causal.py`) with no network calls and
  no new third-party dependencies.
- Produce `causal_weight` values in the closed range `[0.0, 1.0]` with
  stable rounding to 3 decimals so audit comparisons are deterministic.
- Annotate `ValidationRun.counterexample` (already part of the F-133
  schema) with a `causal` sub-record when the causal gate adds new
  information, but never replace an existing symbolic countermodel.
- Add `causal_weight` and `causes` columns to the optional structural
  metadata documented in §13 (`metadata.lkb.causes`), gated behind
  `F-141_ENABLED` in `clawcodex_ext/feature_gate.py`.
- Provide an explicit `override_causal(reason=…, weight=…)` path on
  `LogicalKanbanService` that writes a `human_override` audit event
  with `approver` and `justification`, satisfying §26 (`S-8`).
- Reuse the validation cache key from §13.3 — adding `solver="causal"`
  to the cache tuple — so a re-run with identical facts + causal graph
  is a single-digit-millisecond cache hit.
- Never invoke the causal gate when F-126 is disabled; treat the feature
  as feature-gated just like F-138 Layer 2+.

## Acceptance Criteria

- `tests/logical_kanban/test_causal_layer.py` covers the verb surface,
  the weight thresholds, the synthetic graph seeding rules, and the
  dual-layer gate order (symbolic fail wins; causal weak yields a
  warning but does not flip a pass).
- Calling `intervene.do` on a graph with no `Causes` metadata returns
  `causal_effect=0.0`, `is_significant=false`, `mechanism="null"` —
  never a crash.
- An edge whose source task sets `metadata.lkb.causes = [{target, weight}]`
  with `weight >= 0.7` is recorded on the validation run as
  `causal_weight=weight`, `mechanism="direct"`, and `is_significant=true`.
- `LogicalKanbanService.run` continues to return the same commit
  result for proposals that fail the symbolic gate, regardless of what
  the causal gate says — verified by a regression test that injects a
  stub causal engine that always returns `significant`.
- Human override of a `weak` edge produces an `lkb_human_override`
  audit event containing `proposal_id`, `edge`, `justification`, and
  `approver`, written through the F-137 append log path.
- Adding F-141 does not change the public `TaskUpdate` output schema;
  `causal_weight` appears only when the feature gate is on.

## Dependencies

- F-126 (Agent Loop Foundation) — feature gate machinery.
- F-127 (Task Context Adapter) — `FactsSnapshot` is the causal graph's
  primary input.
- F-132 / F-138 Layer 1 — symbolic gate must pass first.
- F-133 (Validation Runs) — `ValidationRun.counterexample` is the
  write-back target.
- F-137 (Persistence and Audit) — `lkb_human_override` event emission.
- F-139 (Security) — the causal engine must inherit the same input
  sanitisation rules as the solver adapters; raw natural-language text
  never enters a weight computation.

## Out of Scope

- Real do-calculus identifiability (back-door, front-door, IV) — the
  in-process engine is deliberately a normalised proxy. A future
  feature can swap in DoWhy or an equivalent library behind the same
  verb surface.
- External CAP daemon compatibility — only the verb semantics are
  preserved.
- Persisting the causal graph across sessions — Phase 1 keeps the
  graph derived from the snapshot at every call, matching the F-137
  in-memory storage phase.