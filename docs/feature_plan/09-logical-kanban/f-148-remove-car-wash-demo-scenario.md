# F-148 Remove Car-Wash Demo Scenario from Default Pattern Library

## Goal

Eliminate the `car-wash` concrete scenario embedded in the F-134 default
pattern library and the surrounding call sites so that the shipped
codebase contains **no domain-specific action** (e.g. 洗车 / 代洗 / 自助
洗车 / 自动洗车, `staff_service`, `self_service`, `AutomaticWash`,
`CarShop`, etc.) in the implementation. The library stays generic;
domain scenarios are delegated to downstream callers who register their
own patterns via `FuzzyPatternLibrary.add(...)`.

The whitelist for allowed words in implementation logic:

- Generic verbs: 做, 完成, 办理, 处理, 取得, 提交, 校验, 通过
- Generic nouns: 距离, 质量, 时间, 状态, 进度, 数量, 主体, 范围
- Connectors and quantifiers: 依赖, 阻塞, 邻近, 马上, 立刻, 附近, 旁边

Anything beyond the whitelist (specific actions such as 洗车, 做饭,
付款, 部署, 审批, etc.) must be supplied by a downstream caller, not
hard-coded in the library.

## Background

F-134 (fuzzy input and multi-world handling) shipped a built-in
`P-SERV-001` pattern that used a `staff_service / self_service /
automatic` interpretation triplet to disambiguate the user's
"洗车" intent. Subsequent features (F-143 LLM-knowledge-facts,
F-144 todowrite fuzzy gate, F-145 disambiguating tokens, F-146
question context, F-147 movement phrase tolerance) all reproduced the
`50-metre car wash` test scenario across their test corpora and design
specs. The wording has calcified:

- `BUILT_IN_PATTERN_LIBRARY.patterns` registers
  `P-SERV-001` with `code="staff_service"`, `code="self_service"`,
  `code="automatic"`, and `formalization="*ServiceWash(...)"`.
- `AmbiguityDetector._refine_interpretations` keeps four hard-coded
  branches keyed off those exact codes (`driving`, `self_service`,
  `staff_service`, `automatic`) — see
  `clawcodex_ext/logical_kanban/ambiguity_detector.py:292-301`.
- `BUILT_IN_PATTERN_LIBRARY.constraints` carries one
  `DomainConstraint(blocks=frozenset({"self_service", "straight_line"}))`
  entry.
- `tests/logical_kanban/test_fuzzy_multiworld.py`,
  `tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py`,
  `tests/logical_kanban/test_f143_llm_facts.py` all reproduce car-wash
  scenarios.
- Design specs `f-143 … f-147` use the car-wash scenario as their
  illustrative example, which propagates the wording into the
  not-yet-implemented features' future tests too.

F-145 already notes that the same shape of bug exists in any domain
that builds P-XXX patterns the same way (payment-method selection,
deployment-environment selection, file-format selection). F-148 is the
companion: remove the demo before more domains get added on top of it.

## Scope

### In-Scope

The following is exhaustive. Anything not listed stays unchanged.

#### Code: `clawcodex_ext/logical_kanban/`

1. **`fuzzy_patterns.py`**

   - **Delete** the entire `P-SERV-001` block at lines 144-173
     (entry, comment, `matcher`, three `Interpretation` objects with
     codes `staff_service / self_service / automatic` and
     formalizations `StaffServiceWash / SelfServiceWash / AutomaticWash`,
     and the `clarification_prompt`).
   - **Delete** the `DomainConstraint(blocks=frozenset({"self_service",
     "straight_line"}))` block at lines 308-314 (including the
     "Self-service car wash usually implies the customer walks to the
     bay." rationale comment).
   - **Rewrite** `_extract_phrase` (line 79-106) so it does not branch
     on the substring `"serv"` in `pattern.pattern_id`, and does not
     branch on the literal `"洗车"` in text. Replace the four
     category-specific branches with a single fallback `return
     text[:60]`. The new behaviour is exactly the old fallback
     behaviour, which is correct for the remaining generic patterns
     (`P-DIST-001`, `P-PROX-001`, `P-TEMP-001`, `P-DEPDIR-001`,
     `P-INFO-001`, `P-ACCEPT-001`).
   - **Update** the default library's overall docstring at the top of
     the file (currently no count, but the leading sentences imply
     car-wash scope) to read more neutrally. The change is "no
     scenario-specific example" wording, not functional.

2. **`ambiguity_detector.py`**

   - **Delete** the four hard-coded branches in
     `_refine_interpretations` at lines 288-301 keyed on
     `interp.code in {"driving", "self_service", "staff_service",
     "automatic"}`. The remaining `interp.code == "driving"` block is
     covered by step 3 below; the three `staff_service / self_service
     / automatic` blocks (lines 296-301) are deleted outright because
     they have no surviving pattern.
   - **Add** a new private `RefinementRule` Protocol in
     `ambiguity_detector.py`:

     ```python
     class RefinementRule(Protocol):
         def __call__(
             self, text: str, interpretation: Interpretation
         ) -> Interpretation: ...
     ```

     and a `BuiltinRefinementRules` namespace that exposes a single
     `driving_keyword_distance` rule (boost the `driving`
     interpretation when `"驾车" in text or "drive" in
     text.lower()`). The `AmbiguityDetector.__init__` gains an optional
     `refinement_rules` argument that defaults to
     `[BuiltinRefinementRules.driving_keyword_distance]`. The detector
     then runs each rule per matched interpretation.

     This keeps the existing "驾车 / drive" boost behaviour but pushes
     the rule off the hard-coded `interp.code == "driving"` branch so
     the detector no longer references a specific pattern's codes by
     name. Other patterns opt in by adding `refinement_rules=
     (...,)` to their `FuzzyPattern` (a new field on `FuzzyPattern`
     — see step 4 below).

   - **Update** `_build_llm_fallback_prompt` (line 213-214) so the
     illustrative example is not domain-specific:

     ```json
     {"kind": "semantic_vagueness", "interpretations": [{"code": "option_a",
     "formalization": "Estimate({entity}, {value})", "confidence": 0.6}]}
     ```

     `Estimate({entity}, {value})` is a generic placeholder that
     carries no scenario semantics. The phrase `50 米开外那儿洗车` in
     test-fixture JSON is unchanged — that file is in `tests/` and is
     replaced separately.

   - **Schema addition on `FuzzyPattern`** (this is the only field
     added; backward-compatible):

     ```python
     refinement_rules: tuple[Callable[[str, Interpretation], Interpretation], ...] = ()
     ```

     The detector loops over the pattern's `refinement_rules` before
     normalisation, the same way it loops over the builtin rule set.
     Empty tuple preserves current behaviour for patterns that don't
     declare one.

3. **`__init__.py`**

   - **Export** `BuiltinRefinementRules` (new symbol).
   - All other names already exported continue to be exported.

#### Code: tests

4. **`tests/logical_kanban/test_fuzzy_multiworld.py`** (338 lines)

   - **Rename** `test_detects_service_mode_ambiguity` to
     `test_mode_disambiguation_returns_generic_pattern_or_none`.
     Replace the input `"我要洗车"` with three generic inputs
     (`"做事"`, `"完成"`-only, `"完成动作"`-suffixed) and assert
     `severity != "critical"` for the generic inputs (i.e. the
     detection returns no P-SERV-001-style ambiguity). The test now
     proves the demo pattern is gone, not that one still exists.
   - **Rewrite** `test_domain_constraint_prunes_invalid_world`. The
     test must no longer depend on P-SERV-001 codes. Add a
     registration inline via
     `FuzzyPatternLibrary().add(...).add_constraint(...)` that
     constructs two patterns and one constraint over generic codes
     (e.g. `option_a / option_b` and a constraint
     `blocks=frozenset({"option_x", "option_y"})`). The assertion
     shape stays the same.
   - **Replace** every `phrase="洗车"` and `"洗车" in text` literal
     with a generic phrase such as `phrase="做某事"`.
   - **Replace** every distance-related car-wash input
     (`"离家50米的洗车店"`, `"离家50米"`, `"开车离家50米"`,
     `"自助洗车离家50米"`) with generic placeholders:
     - `"距离 100"` (for P-DIST-001)
     - `"距离 100，做事方式未定"` (for combined mode tests, after the
       new behaviour is documented)
     - `"100 公里，开车过去"` (for the driving boost test)
   - **Update** `TestClarification.test_user_clarification_overrides_assumption`
     so the detector input reads `"距离 100（公里）"`, and the
     `assumed_value` reads `"walking"` (or whatever name P-DIST-001's
     interpretation is renamed to — see step 6).
   - **Update** `TestServiceIntegration.test_evaluate_assertion_returns_worlds`
     input from `"离家50米的洗车店"` to `"距离 100（公里）"`.

5. **`tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py`** (347
   lines)

   - **Rename** `test_car_wash_input_is_denied` to
     `test_distance_disambiguation_input_is_denied`.
   - **Replace** the input string with a generic one that still
     triggers P-DIST-001:
     `"距离 100，做事方式未定（或澄清）"`. The expected
     `clarification_prompt` is `"您说的距离是指步行距离、直线距离还是驾车距离？"`
     (kept because the prompt wording itself is generic and only the
     code identities change — see step 6).

6. **`tests/logical_kanban/test_f143_llm_facts.py`** (418 lines)

   - **Rename** `TestCarWashRegression` to
     `TestGenericDistanceRegression`.
   - **Rename** `test_fifty_meter_car_wash_passes_with_llm_fact` to
     `test_generic_distance_passes_with_llm_fact`.
   - **Replace** the two task subjects with generic ones:
     - `"vehicle"` stays (it's an entity, not a verb).
     - `"car_shop"` becomes `"task_x"` or similar generic entity.
     - `subject="50 米开外那儿洗车"` becomes
       `subject="距离 100，单位待定"` or similar.
   - The LLM stub JSON payload remains `"predicate": "Requires"`,
     `"args": ["vehicle", "task_x"]`, `"source": "llm_extracted"`,
     `"confidence": 0.7` — generic predicate / generic entities / no
     scenario wording.

#### Docs: `docs/feature_plan/09-logical-kanban/`

7. **`f-143-runtime-llm-knowledge-facts.md`**

   - **Replace** the phrase "50-metre car wash walkthrough" and any
     `"50 米开外那儿洗车"` mention with a generic phrase such as
     "the generic distance-and-mode walkthrough" and `"距离 100"`.
   - **Replace** the reproduction-input examples with generic
     variants.
   - The doc lists F-148 itself as the parent feature for the
     walkthrough update.

8. **`f-144-todowrite-fuzzy-gate-coverage.md`**

   - **Replace** "car-wash reproduction was the simplest case that
     exercised the gap; the gap is structural." with "the
     distance+mode reproduction was the simplest case that exercised
     the gap; the gap is structural."
   - No other changes; F-144's scope statement is already
     domain-agnostic.

9. **`f-145-disambiguating-token-confidence-booster.md`** (full
   rewrite of illustrative examples only; schema design unchanged)

   - **Replace** every `代洗 / 自助 / 自动 → staff_service /
     self_service / automatic` triple with a generic example using
     priorities:
     `"紧急" / "普通" / "不急" → "high_priority" / "medium_priority"
     / "low_priority"`.
   - **Replace** the inline P-SERV-001 snippet with an inline
     P-PRIORITY-001 snippet (a new pattern the document proposes but
     does **not** ask F-148 to ship).
   - **Rename** any `P-SERV-001` reference to `P-PRIORITY-001` or
     generic `FuzzyPattern` wording.
   - **Update** the acceptance-criteria test-file references
     (`test_f145_disambiguating_tokens.py`) to use the priority
     example, not the car-wash one. The file does not exist yet —
     F-145 is not implemented; this rewrite prevents the upcoming
     implementation from inheriting the demo.

10. **`f-146-question-vs-premise-context.md`**

    - **Replace** all `"去自助洗车还是代洗"`, `"我要代洗车"`,
      `"代洗"` mentions with `紧急完成 vs 普通完成`,
      `我要优先完成`, `紧急` respectively.
    - The schema and pipeline design are unchanged.

11. **`f-147-movement-phrase-matcher-tolerance.md`**

    - **Replace** all of:
      - `"去洗车"` → `"去做事"`
      - `"我刚从洗车店出来"` → `"我刚从 X 处出来"`
      - `"我正在洗车"` → `"我正在做事"`
      - `"我喜欢洗车"` → `"我喜欢做事"`
    - **Replace** the "non-reproduction-domain" inputs (e.g. `"我要去
      取快递"`) with priority + completion oriented examples
      (`"我要优先完成 X"`, `"我要普通完成 X"`, `"我要延迟完成 X"`)
      so all remaining examples are in the same generic frame.

### Out of Scope

- The `P-DIST-001` interpretation codes
  (`on_foot / straight_line / by_vehicle`) are renamed in F-148 PR 1
  to drop the verb "walking / driving"; the new codes describe
  measurement modalities in noun form. F-148 only forbids
  *scenario-bound* actions; the rename reflects that boundary.
- The `P-INFO-001` interpretation codes (`vehicle_at_home /
  vehicle_unknown`) are renamed to `entity_default /
  entity_unknown`. The matcher's verb set changes from
  `去[洗修买吃]` to `去(做|完成|办理)`; the **concept** (where is the
  subject?) is generic. The vehicle-specific code names are renamed
  within F-148.
- Re-designing `FuzzyPattern` schema (priority field, extractor
  field, `requires` field, etc.). F-148 adds exactly one new field
  (`refinement_rules`). Any other schema work is a separate feature.
- F-145 / F-146 / F-147 implementation. Their specs are doc-only edits
  in F-148; their implementation is whoever picks them up next.
- The CLAUDE.md "Common commands" / "Things to know" sections are
  unchanged; they don't reference the car-wash scenario.
- `src/` is unchanged. All edits are inside `clawcodex_ext/`.

## Design Decisions

### D1. Pattern Removal vs. Renaming

`P-SERV-001` is **deleted**, not renamed to `P-MODE-001`. There is no
generic "mode of doing a thing" ambiguity worth shipping as a default;
every concrete mode (car-wash, payment-method, deployment-strategy,
file-format, ...) is domain-specific and should be supplied by the
downstream caller. Keeping a renamed demo would only shift the
scenarios, not remove the demo. The fix is **the demo must not exist
in the default library**.

### D2. `staff_service / self_service / automatic` Codes

These three codes are removed along with `P-SERV-001`. No other
default pattern reuses them; nothing else in the codebase depends on
those code strings. A codebase-wide grep before the PR confirms this
— the search list is in the implementation steps.

### D3. `P-DIST-001` Interpretation Rename

The `P-DIST-001` interpretation codes are renamed from
`walking / straight_line / driving` to `on_foot / straight_line /
by_vehicle`. The middle code is already neutral. The corresponding
`formalization` strings are renamed from
`WalkingDistance / EuclideanDistance / DrivingDistance` to
`FootDistance / EuclideanDistance / VehicleDistance`. The conceptual
ambiguity (how is the distance measured?) is preserved; only the
naming moves from verb-form to noun-form.

The `BuiltinRefinementRules.driving_keyword_distance` rule keeps its
matcher (`"驾车" in text or "drive" in text.lower()`) but bumps the
interpretation whose code is `"by_vehicle"`. The rule name is a
historical artefact and stays.

### D4. DomainConstraint Pruning Test Rewriting

`test_domain_constraint_prunes_invalid_world` was car-wash-coupled.
Two ways to keep coverage of `_prune`:

- **Chosen**: rewrite the test as a *mechanism* test (deferred to PR 2).
  The test registers two inline `FuzzyPattern` objects with codes
  `option_a / option_b / option_x / option_y` plus a
  `DomainConstraint(blocks=frozenset({"option_x", "option_y"}))`. The
  assertion shape is unchanged.

- **Not chosen**: keep a minimal default `DomainConstraint` (e.g.
  `blocks=frozenset({"by_vehicle", "instant_distance"})`) just so the
  old test keeps passing. This re-introduces domain-specific tokens
  into the default library and contradicts F-148's goal.

### D5. Disambiguating-Token Refactor in F-145

F-145 uses the car-wash codes as its worked example. F-148 **does not
implement** F-145. F-148 rewrites only the *illustrative snippets* in
F-145 so that, when F-145 lands, its tests are forced to use a
priority example. The schema design (`DisambiguatingToken` field on
`FuzzyPattern`) is unchanged.

### D6. P-INFO-001 Verb Set

`去[洗修买吃]` becomes `去(做|完成|办理)`. "做 / 完成" are the user's
declared whitelist; "办理" is a generic procedural verb and is
included as the third option only to keep three demonstrative
patterns. If reviewers prefer a single verb, the regex simplifies to
`r"去做|去完成"` and the doc note is updated accordingly.

### D7. `RefinementRule` Protocol

The driving boost that used to be hard-coded lives on as
`BuiltinRefinementRules.driving_keyword_distance`. This is the only
builtin rule. It bumps the interpretation whose code is `"by_vehicle"`
when `"驾车" in text or "drive" in text.lower()` — the same logic
that existed before F-148, just relocated. New patterns opt in via
the new `FuzzyPattern.refinement_rules` field. The shape
`Callable[[str, Interpretation], Interpretation]` matches the
`DisambiguatingToken.boosted_confidence` pattern from F-145, so when
F-145 lands the two mechanisms can share a registry.

## Implementation Steps

Each step is a self-contained, revertible PR.

### PR 1 — Library cleanup (no test changes)

- File: `clawcodex_ext/logical_kanban/fuzzy_patterns.py`
  - Delete `P-SERV-001` (lines 144-173).
  - Delete the `DomainConstraint(blocks=frozenset({"self_service",
    "straight_line"}))` block (lines 308-314).
  - Rewrite `_extract_phrase` (lines 79-106) to drop the `"serv"` /
    `"洗车"` branches and all six category-id substring branches; the
    only fallback is `text[:60]`.
  - Rename `P-DIST-001` interpretation codes from
    `walking / straight_line / driving` to
    `on_foot / straight_line / by_vehicle` and corresponding
    `formalization` strings from
    `WalkingDistance / EuclideanDistance / DrivingDistance` to
    `FootDistance / EuclideanDistance / VehicleDistance`.
  - Rename `P-INFO-001` interpretation codes from `vehicle_at_home /
    vehicle_unknown` to `entity_default / entity_unknown` and the
    `formalization` strings to `AtDefault({subject})` and
    `AtUnknownLocation({subject})`.
  - Widen `P-INFO-001` matcher from `去[洗修买吃]` to `去(做|完成|办理)`.
- File: `clawcodex_ext/logical_kanban/ambiguity_detector.py`
  - Add `RefinementRule` Protocol.
  - Add `BuiltinRefinementRules` namespace with
    `driving_keyword_distance` (bumps the interpretation whose code
    is `"by_vehicle"`).
  - Rewire `_refine_interpretations` to walk
    `[s for s in self.refinement_rules]` plus
    `[r for p in patterns for r in p.refinement_rules]`. Remove the
    three hard-coded branches keyed off
    `staff_service / self_service / automatic`.
  - Update `_build_llm_fallback_prompt` example to
    `Estimate({entity}, {value})`.
- File: `clawcodex_ext/logical_kanban/fuzzy_patterns.py` schema
  - Add `FuzzyPattern.refinement_rules: tuple[Callable[[str,
    Interpretation], Interpretation], ...] = ()`.

Expected diff: 1 library file substantive + 1 detector file
substantive + 1 schema addition + 1 export. **No test changes in this
PR.** All existing tests that referenced the demo are expected to
**fail**; this is intentional and surfaces them for PR 2.

### PR 2 — Test re-wiring (multiple test files)

- Rewrite each test listed in scope items 4, 5, 6 according to the
  new inputs.
- Rename `TestCarWashRegression` → `TestGenericDistanceRegression`,
  etc.
- Add the inline `FuzzyPatternLibrary.add(...)` construction in
  `test_domain_constraint_prunes_invalid_world`.
- After PR 2 lands, all previously-failing tests now pass on the
  cleaned-up library, and the only remaining failures (if any) are
  unintended.

Expected diff: 3 test files substantive. Library untouched in PR 2.

### PR 3 — Docs re-wording

- Rewrite the car-wash examples in `f-143 … f-147` specs according
  to scope items 7, 8, 9, 10, 11. No code change.

Expected diff: 5 doc files updated, all `f-NN-*.md` only.

### PR 4 — F-148 spec lands

- Add this document (`f-148-remove-car-wash-demo-scenario.md`) to
  the plan directory.
- Update `README.md` feature table to register F-148 as a P1 entry,
  parent of F-143 walkthrough update.

Expected diff: 1 new doc + 1 README table row.

## Acceptance Criteria

After all four PRs merge:

- **Code surface**: `grep -nE "洗车|代洗|StaffServiceWash|SelfServiceWash|AutomaticWash|staff_service|self_service"` over `clawcodex_ext/logical_kanban/` and
  `tests/logical_kanban/` returns **zero matches**. (Reserved words:
  the strings `walking / straight_line / driving`, the existing
  `driving_keyword_distance` rule, and the new generic patterns.)
- **Test corpus**:
  `python3 -m pytest tests/logical_kanban/test_fuzzy_multiworld.py tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py tests/logical_kanban/test_f143_llm_facts.py -q`
  passes with zero warnings.
- **Library contents**:
  ```python
  from clawcodex_ext.logical_kanban import BUILT_IN_PATTERN_LIBRARY
  pattern_ids = {p.pattern_id for p in BUILT_IN_PATTERN_LIBRARY.patterns}
  assert pattern_ids == {
      "P-DIST-001", "P-PROX-001", "P-TEMP-001",
      "P-DEPDIR-001", "P-INFO-001", "P-ACCEPT-001",
  }
  ```
  passes.
- **No leftover constraint**: `BUILT_IN_PATTERN_LIBRARY.constraints
  == ()`. The `test_domain_constraint_prunes_invalid_world` test now
  builds its own library inline.
- **Detector still boosts**: the rewritten
  `test_by_vehicle_context_boosts_by_vehicle_interpretation` confirms
  the `driving_keyword_distance` rule still produces the same
  confidence ordering as the original.
- **Stability gate**: `python3 -m pytest tests/stability_gate/ -q
  --tb=short -x` continues to pass. The LKB-related stages (5 / 6)
  are unchanged in expected runtime.
- **CI ruff**: `ruff check clawcodex_ext/logical_kanban/ tests/logical_kanban/` reports zero new findings.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| A downstream consumer outside this repo relies on the literal `staff_service / self_service / automatic` codes or `P-SERV-001`. | `grep`-checked before merge across this repo. No other repo surfaces them. If breakage is reported after merge, F-148 ships a one-line deprecation shim in a follow-up (out of scope here). |
| Renaming `vehicle_at_home / vehicle_unknown` breaks the explain / repair UI which renders `interpretation.code` to humans. | The explain layer (`explain.py`) reads the code verbatim; renaming is propagated by changing the pattern definitions only. The UI text falls under "routing distance" not car-wash semantics, so the rename is safe. |
| `_refine_interpretations` removing the three car-wash branches regresses F-145's worked example. | F-145 is not implemented yet; PR 3's doc rewrite gives the next implementer the priority example that doesn't need those branches. |
| The inline library construction in `test_domain_constraint_prunes_invalid_world` is verbose. | Accepted as the cost of a *mechanism* test. The verbosity is bounded (one extra `add()` chain). |
| Removing the sole default `DomainConstraint` empties `BUILT_IN_PATTERN_LIBRARY.constraints`. | The list is empty by default; downstream callers add constraints via `library.add_constraint(...)`. The shape is unchanged. |

## Rollback

- PR 1 is reversible by re-adding the deleted `P-SERV-001` block and
  the `DomainConstraint` block from the F-134 commit
  (`70309597`). Revert the schema additions on `FuzzyPattern` and the
  Protocol / namespace additions in `ambiguity_detector.py` in the
  same revert.
- PR 2 is reversible by restoring the deleted test methods from the
  same F-134 commit; the test file is checked into git history.
- PR 3 is reversible by checking out the previous `f-143 … f-147`
  spec content; no other layer depends on the wording.
- PR 4 is reversible by removing this document and the README table
  row.

## Dependencies

- F-134 (fuzzy input and multi-world handling) — supplies the
  `FuzzyPattern` / `FuzzyPatternLibrary` / `AmbiguityDetector` /
  `WorldGenerator` / `DomainConstraint` shapes F-148 edits.
- F-143 (runtime LLM knowledge facts) — its walkthrough text is
  updated as part of F-148's PR 3.
- F-144 (legacy todo fuzzy gate) — its tests exercise the default
  library; cleaned up as part of PR 2.
- F-145 / F-146 / F-147 (forward-looking specs) — their illustrative
  examples are reworded as part of PR 3.

## Out of Scope (re-stated, for reviewers)

- `P-DIST-001` interpretation codes (`walking / straight_line /
  driving`) are kept. They are measurement modalities, not
  scenario-specific actions.
- `FuzzyPattern` schema additions beyond the single
  `refinement_rules` field. Priority / extractor / requires / etc.
  remain separate features.
- F-145 / F-146 / F-147 implementation. F-148 only updates their docs.
- Any re-architecture of `world_generator._prune`. The soft/hard
  constraint split is a separate refactor.
- Re-bundling the LLM-fallback prompt to use Chinese examples. The
  example is now `Estimate(...)` regardless of locale.

## Verification Snapshot (post-merge)

```bash
# 1) Clean grep
grep -nE "洗车|代洗|StaffServiceWash|SelfServiceWash|AutomaticWash|staff_service|self_service|automatic" \
  /mnt/c/WorkSpace/clawcodex/clawcodex_ext/logical_kanban/*.py \
  /mnt/c/WorkSpace/clawcodex/tests/logical_kanban/*.py

# 2) Library content
python3 -c "from clawcodex_ext.logical_kanban import BUILT_IN_PATTERN_LIBRARY; \
print(sorted(p.pattern_id for p in BUILT_IN_PATTERN_LIBRARY.patterns))"

# 3) Tests
python3 -m pytest tests/logical_kanban/test_fuzzy_multiworld.py \
  tests/logical_kanban/test_f144_todowrite_fuzzy_gate.py \
  tests/logical_kanban/test_f143_llm_facts.py -q --tb=short

# 4) Stability gate
python3 -m pytest tests/stability_gate/ -q --tb=short -x

# 5) Lint
ruff check clawcodex_ext/logical_kanban/ tests/logical_kanban/
```

A pass on all five commands is the F-148 acceptance bar.
