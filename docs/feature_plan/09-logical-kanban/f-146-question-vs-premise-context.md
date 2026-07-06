# F-146 Question-Context Suppression for Interpretation Refinement (P1)

## Goal

Stop `AmbiguityDetector._refine_interpretations` (and the
disambiguating-token booster introduced in F-145) from boosting an
`Interpretation` when the matching keyword appears inside a
**question frame**, not a **premise**. The fix is
`Interpretation`-agnostic: any keyword → any code that currently
relies on a substring test must check the surrounding linguistic
context before applying the boost.

A user asking *"I should go by car, right?"* should not push the
`driving` interpretation the same way a user asserting *"I will go
by car"* should. The same logic applies symmetrically to every
transportation / choice-of-action interpretation the pattern
library defines.

## Background

Reproduced on 2026-07-06 in the F-143 walkthrough. The
reproduction input was a Chinese natural-language task description
ending with a question that contained the keyword
`"开车"`. The detector reported:

```
walking       0.3529    base 0.60
straight_line 0.2353    base 0.40
driving       0.4118    base 0.00, _refine_interpretations boosted to 0.70
```

The boost was wrong: the user was asking whether to drive, not
stating that they would. The current `_refine_interpretations`
rule was:

```python
if interp.code == "driving" and (
    "开车" in text or "驾车" in text or "drive" in text.lower()
):
    confidence = 0.70
```

The substring test ignores whether the keyword sits inside a
question frame. A symmetric problem exists for any other
transportation / choice-of-action keyword in the pattern library
(`"步行"`, `"坐地铁"`, `"叫外卖"`, etc.) — once added, they would
inherit the same bug.

The bug is in the **mechanism** (substring test ignoring
linguistic context), not in the specific `driving` rule. The
fix generalises.

## Scope

### Question-Frame Helper

A new module-private helper
`_is_question_context(text, target_word, *, pre_window=8,
post_window=4) -> bool` in `fuzzy_patterns.py`. It returns
`True` when any of the following is true:

- **Pre-window markers** (8 characters before `target_word`):
  `该不该`, `是不是`, `还是`, `要不要`, `吗`, `呢`, `哪`,
  `怎么`, `哪种`, `?`, `？`.
- **Post-window markers** (4 characters after `target_word`):
  `还是`, `或`, `or`, `?`, `？`.
- The 8 / 4 character window is character-based because the
  patterns are mixed Chinese / English; it is calibrated against
  the failing inputs in `tests/logical_kanban/test_fuzzy_multiworld.py`
  plus the F-143 walkthrough reproduction.

### Application Sites

`_refine_interpretations` and the F-145
`_apply_disambiguating_tokens` both consume the new helper. The
helper replaces the bare substring test that currently drives
every boost:

```python
# Before
if interp.code == "driving" and (
    "开车" in text or "驾车" in text or "drive" in text.lower()
):
    confidence = 0.70

# After
if interp.code == "driving" and (
    "开车" in text or "驾车" in text or "drive" in text.lower()
) and not _is_question_context(text, "开车"):
    confidence = 0.70
```

The same shape of guard wraps every other keyword-driven
refinement in the file (`"紧急"`, `"普通"`, `"不急"`,
`"步行"`, `"公交"`, `"地铁"`, etc.). A new test
parameterisation enforces that **every** `DisambiguatingToken`
declared in any `FuzzyPattern` (built-in or custom) is wrapped
with the question-frame guard — if a future pattern omits the
guard, the test fails with a clear "missing question-frame
guard" message.

### Pattern-Local Change

The fix is fully contained in `AmbiguityDetector._refine_interpretations`,
the new `_apply_disambiguating_tokens` (F-145), and the new
`_is_question_context` helper. No public API change. No schema
change. No new field on `Ambiguity` or `AmbiguityReport`.

## Requirements

- `_is_question_context(text, target_word)` returns `True` for the
  test strings enumerated in the Acceptance Criteria below and
  `False` otherwise.
- `_refine_interpretations` skips the boost for any
  `Interpretation.code` whose keyword is inside a question frame.
- `_apply_disambiguating_tokens` (F-145) skips the boost for any
  `DisambiguatingToken.keyword` inside a question frame.
- A new `tests/logical_kanban/test_f146_question_context.py`
  parameterised test asserts that every `DisambiguatingToken` in
  the built-in library (and any test-registered custom pattern)
  is wrapped with the question-frame guard. A pattern that
  omits the guard fails the test with a clear message.
- The detector's wall-clock impact is bounded: `_is_question_context`
  is a single pass over the 8- or 4-character window. The unit test
  asserts the full `detect(...)` call stays under 5 ms on the dev
  reference box for inputs up to 200 characters.

## Acceptance Criteria

- `tests/logical_kanban/test_f146_question_context.py`:
  - The reproduction input from the bug report now reports
    `driving` at confidence **0.00** (renormalised to whatever the
    walking / straight-line pair leaves behind), with `walking`
    remaining the top interpretation at the 0.60 base.
  - Premise-style inputs (`"我要开车去 50 米外"`,
    `"I'll drive there"`) still boost `driving` to 0.70
    (regression coverage).
  - Question-framed inputs for **at least three** different
    `Interpretation.code` values are covered: `driving`
    (`"我该开车过去吗"`), `walking` (`"我该走路去吗"`), and
    a custom `Subway` interpretation registered in-test
    (`"我该坐地铁去吗"`). All three must skip the boost.
  - A new mixed-domain input `"紧急完成还是普通完成？"` reports
    `high_priority` and `medium_priority` at the default base
    confidences, not the hint-boosted 0.95 values, because the
    keywords are inside the question frame.
- The parameterised "every `DisambiguatingToken` has a guard" test
  passes for the built-in library and for two in-test registered
  custom patterns.
- `tests/logical_kanban/test_fuzzy_multiworld.py::test_driving_context_boosts_driving_interpretation`
  is updated to use a premise-style input and continues to assert
  `driving` is the top interpretation.
- All other F-134 / F-145 tests continue to pass without
  modification.

## Dependencies

- F-134 (Fuzzy Input and Multi-World Handling) — the helper and the
  refinement logic are touched.
- F-145 (Disambiguating Tokens as Confidence Boosters) — F-146 must
  compose with F-145, not regress it. The hint boost for
  `"紧急"` in a premise (`"我要紧急完成"`) must still push
  `high_priority` to 0.95; F-146 only suppresses boosts for
  question-framed occurrences.

## Out of Scope

- Full Chinese sentence-segmentation. The 8-character window is a
  pragmatic heuristic; introducing jieba or HanLP is a much larger
  effort and not justified by the current failure rate.
- Suppressing boosts for *all* modal verbs (`"要"`, `"想"`,
  `"准备"`). The question-frame heuristic is narrow by design.
- A user-configurable marker list. The set of pre-window /
  post-window markers is fixed in code; any new marker is a
  follow-up feature with its own F-N.
- English-only question detection (`"?  right?"`, `"should I"`).
  The MVP keeps the mixed-script heuristic; full English coverage
  is a follow-up.
