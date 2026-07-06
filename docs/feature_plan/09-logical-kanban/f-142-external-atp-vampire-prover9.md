# F-142 External ATP: Vampire, Prover9 (LADR-2026), and Mace4

## Goal

Replace the in-process FOL saturation prover shipped as F-138 Layer 5
(`atp-tptp`) with an optional external Automated Theorem Prover (ATP)
subprocess path that the same `SolverAdapter` contract can drive. When
the binaries are installed the pipeline picks up richer proofs and
real counterexamples; when they are absent the in-process Layer 5 from
F-138 keeps the pipeline green, preserving the conservative
aggregation policy from spec §10.7.

This feature is intentionally additive. No existing `TaskUpdate` output
or solver adapter name changes; no new public tool surface.

## Scope

### Engine Roster

Mirroring spec §10.5:

| Role | Primary | Fallback | Counterexample |
| --- | --- | --- | --- |
| Pure FOL theorem proving | Vampire | Prover9 (LADR-2026) | Mace4 |
| TPTP compatibility quirks | Prover9 (LADR-2026) | Vampire | Mace4 |
| Theory-bearing fragments | Z3 (F-138 Layer 4) | — | Z3 model |

### Adapter Surface

Each engine is wrapped by a `SolverAdapter` subclass that conforms to
the F-138 contract:

- `name` ∈ `{atp-vampire, atp-prover9, atp-mace4}`
- `available()` probes the binary with `<bin> --version` and caches the
  result for the lifetime of the process.
- `solve(request)` translates the `FactsSnapshot` to TPTP FOF (see
  below), spawns the binary through `run_external_solver` so the
  F-139 resource limits apply, parses the SZS status line, and returns
  a `SolverResponse` whose `proof_trace` and `counterexample` fields are
  populated for `Theorem` and `CounterSatisfiable` outcomes
  respectively.
- Adds the adapter name to the existing `extended_adapters()` factory
  (already exposed by F-138) without renaming or removing the
  in-process `atp-tptp` adapter.

### TPTP FOF Generator

Extend the existing `solver_atp.py::emit_tptp_program` (or replace its
single consumer) into a standalone helper
`build_tptp_program(snapshot, request) -> str` that:

- emits each task as `tptp(task(t, "subject_h1234"))` etc. with all
  user-controlled strings pre-sanitised by `encode_solver_literal`
  (F-139),
- maps the F-132 rule set (R-001 … R-006, LKB-TRANSITION-001) to TPTP
  FOF using the standard symbol table from spec §6.4
  (`∀→!`, `∃→?`, `¬→~`, `∧→&`, `∨→|`, `→=>`, `↔<=>`),
- wraps the chosen transition in a `conjecture(...)` block so the
  binary returns `Theorem` for valid proposals and
  `CounterSatisfiable` for invalid ones, and
- records the generated program on the `ValidationRun` as
  `solver_syntax: "tptp-fof"` for audit (the §13 schema already
  documents this field).

### SZS Status Parser

`parse_szs_status(stdout: str) -> SolverResult` consumes the standard
SZS output (`% SZS status Theorem …`) and maps:

| SZS token | `SolverResult` | Adapter behaviour |
| --- | --- | --- |
| `Theorem` | `pass` | Populate `proof_trace` from the `% SZS output start … end` block |
| `CounterSatisfiable` | `fail` | Populate `counterexample` from the model section |
| `Timeout` / `ResourceOut` | `timeout` | Surfaces through F-138's existing timeout policy |
| `Satisfiable` (Mace4 only) | `fail` | Treat as a finite countermodel; copy into `counterexample` |
| `Error` / `Unknown` | `error` | Surfaces through the F-138 `error_info` channel |

### Mace4 Portable → JSON Parser

Mace4 emits a portable counterexample block
(`% Interpretation: …`). A dedicated parser
`parse_mace4_interpretation(stdout: str) -> dict[str, Any]` converts it
into the `countermodel` shape already declared in the F-133 schema —
one entry per task showing the assignment that violates the
conjecture.

### Async Layer 5

Per spec §10.1 and §22.4, external ATP runs are **fully async**: they
never block the synchronous commit path. The pipeline exposes a new
`validate_async(...)` coroutine that schedules the subprocess on the
shared `run_external_solver` resource pool (default
`SolverResourceLimits(timeout_seconds=60, max_memory_mb=512,
max_output_bytes=65536)` per spec P-6). The async result feeds into
`ValidationRun.counterexample` and `ValidationRun.proof_trace` after the
synchronous symbolic gates have already returned, so a slow Vampire run
never delays a `TaskUpdate`.

### Write-Back: Proof Trace and Countermodel

The synchronous pipeline emits a `validation_run` whose
`solver_results[].adapter` is one of the existing F-138 names. When the
external ATP finishes asynchronously, the runtime appends an
`lkb_proof_enrichment` audit event that updates the
`ValidationRun.proof_trace` and `ValidationRun.counterexample` fields
without rewriting the immutable `result`. UI consumers (F-136) detect
the enrichment via the event log and refresh their cached display.

### LLM Annotation Tag Separation

`explain.py` (F-136) receives the same `ValidationRun` plus an extra
`proof_enrichment` channel. When building the model-facing summary the
renderer tags LLM-generated annotations with `[llm]` and machine-checked
proof lines with `[proof]`, so the two cannot be visually confused. The
tags are rendered as plain text prefixes — no Markdown emphasis — to
keep the conservative "tag separation" guarantee from spec §22.4.

## Requirements

- Add three adapters under `clawcodex_ext/logical_kanban/atp/`:
  `vampire.py`, `prover9.py`, `mace4.py`. Each re-uses the F-138
  `SolverAdapter` ABC and the F-139 `run_external_solver` helper.
- Extend `extended_adapters()` to append the new adapters when their
  binaries are present, in the order `atp-vampire, atp-prover9,
  atp-mace4` (after Layer 1–4). The factory must remain pure: no I/O
  beyond the `--version` probe that already exists on
  `SolverAdapter.available()`.
- Implement `build_tptp_program`, `parse_szs_status`, and
  `parse_mace4_interpretation` as standalone, side-effect-free
  functions that can be unit-tested with fixture stdout.
- Wire `LogicalKanbanService.validate_async` into the runtime cache so
  the result keys off `(facts_hash, ruleset_hash, canonical_ir_hash,
  solver, solver_version, policy_version)` exactly as the F-138 cache
  does — no new cache dimensions.
- Emit `lkb_proof_enrichment` audit events through the F-137 append
  log; events must be idempotent under retry (same enrichment key →
  no duplicate emission).
- Keep the existing in-process `atp-tptp` adapter and tests intact so
  CI remains green on machines without Vampire/Prover9/Mace4.

## Acceptance Criteria

- A test that mocks `vampire` to print
  `% SZS status Theorem\n% SZS output start\n[proof]\n…\n% SZS output end`
  sees `result='pass'`, `proof_trace` populated, and the TPTP program
  written to a per-test temp directory that is removed on teardown.
- A test that mocks `mace4` with a known portable counterexample sees
  `result='fail'`, `counterexample` populated with the expected
  per-task assignment, and the failure rule attributed to the
  violated R-code.
- When `vampire` is absent, `atp-vampire.available()` returns `False`
  and the adapter does not appear in `extended_adapters()`. The
  pipeline still runs and the in-process `atp-tptp` continues to back
  Layer 5.
- `validate_async` completes within `SolverResourceLimits.timeout_seconds`
  on the slow path (asserted via `asyncio.wait_for` in tests) and never
  raises into the calling coroutine — exceptions are converted into
  `ValidationRun` records with `result='error'` and an `error_info`
  payload.
- The synchronous `TaskUpdate` latency (Layer 1 + Layer 2 path) is
  unchanged from the F-138 baseline; verified by a regression test that
  asserts the elapsed wall-clock is under 200ms with all external ATP
  adapters configured but absent.
- `lkb_proof_enrichment` events are emitted at most once per
  `(validation_run_id, adapter)` tuple under retry, verified by an
  idempotency test that calls the enrichment path twice with identical
  inputs.
- LLM annotations on enriched runs are tagged `[llm]` and machine
  proofs are tagged `[proof]`; a snapshot test pins the rendered
  output so future changes must update the fixture deliberately.

## Dependencies

- F-126 — feature gate machinery (`F-142_ENABLED`).
- F-127 — `FactsSnapshot` is the input to the TPTP generator.
- F-132 — Layer-1 rules are the source of the TPTP axioms.
- F-133 — `ValidationRun.proof_trace` and `.counterexample` are the
  write-back targets.
- F-136 — `explain.py` consumes the tag-separated annotations.
- F-137 — `lkb_proof_enrichment` audit event emission.
- F-138 — base `SolverAdapter` contract, `SolverPipeline` aggregation,
  and the in-process `atp-tptp` adapter that stays as the fallback.
- F-139 — `run_external_solver`, `SolverResourceLimits`, and
  `encode_solver_literal` are the security/safety substrate.

## Out of Scope

- Linking Vampire/Prover9 as native libraries. Per spec §26 the
  invocation is strictly via subprocess; this avoids the GPLv2
  obligation that would attach to direct Prover9 linking.
- Theory reasoning (arithmetic, arrays, inductive datatypes). Those
  fragments continue to route through the F-138 Layer 4 Z3 adapter.
- Lean protocol-level verification — that lives in spec §22.5 and is a
  separate feature beyond the MVP 3 scope of this document.