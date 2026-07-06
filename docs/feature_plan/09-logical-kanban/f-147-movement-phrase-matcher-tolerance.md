# F-147 Movement-Phrase Matcher Tolerance (P1)

## Goal

Fix the structural brittleness of the `missing_subject` matcher
(`P-INFO-001`) so it captures the natural ways users express
"going somewhere to do X" in Chinese, English, and mixed text. The
fix is a general-purpose **verb-phrase matcher tolerance** layer,
not a wash-task-specific patch.

## Background

Reproduced on 2026-07-06. The P-INFO-001 matcher is:

```python
matcher=lambda t: bool(
    re.search(r"去[洗修买吃]", t) and not re.search(r"从|在", t)
),
```

The regex `去[洗修买吃]` requires the `去` and the verb character
to be **adjacent**. Real users rarely write that terse: the F-143
reproduction input writes a movement phrase with the verb several
characters after `去`, and a follow-up question writes
`"开车过去"` where the verb `过去` is not in the matcher character
class. Both miss.

The intent of P-INFO-001 is to detect *"the user is going
somewhere but has not declared where they currently are"*. That
intent survives a few characters of intervening text, and it
covers a much wider verb / preposition / movement vocabulary
than the original four-character class.

## Scope

### Regex Tolerance

Replace the matcher with a tolerant pattern that allows **0 to 8
characters** of intervening text (Chinese, English letters, or
punctuation) between `去` and the verb character:

```python
matcher=lambda t: bool(
    re.search(r"去.{0,8}?[洗修买吃订取寄送办]", t)
    and not re.search(r"从|在|刚从|刚从.{0,4}?去", t)
),
```

The verb character class is widened to include common action
verbs that pair with `去`: `洗, 修, 买, 吃, 订, 取, 寄, 送, 办`.
The 8-character window is calibrated against the corpus of
failing inputs in `tests/logical_kanban/test_fuzzy_multiworld.py`
plus the F-143 walkthrough reproduction.

### Colloquial Movement Variants

A new clause to the matcher catches the colloquial movement
variants `出发去`, `前往`, `去到`, and the English `head to`,
`going to`:

```python
or re.search(r"(出发去|前往|去到|head to|going to)", t)
```

These are matched even when the verb character is not present,
because the intent (going somewhere) is already explicit.

### Negative Filter

The `not re.search(r"从|在", t)` clause is preserved but
extended with `刚从` so the detector still skips sentences that
explicitly declare the user is *at* a location.

### Pattern-Local Change

The fix is fully contained in
`fuzzy_patterns._default_library()` (the
P-INFO-001 entry) and the matching `Interpretation` confidences.
No public API change. No schema change. No new field on
`Ambiguity` or `AmbiguityReport`.

## Requirements

- `P-INFO-001` matches all of the following test inputs:
  - `"去洗车"` (regression — original adjacent case)
  - The two reproduction inputs from the F-143 walkthrough.
  - `"我准备出发去吃饭"`, `"请问前往哪里？"`, `"去到店门口"`,
    `"heading to the office"`, `"I'm going to fix this"`.
- `P-INFO-001` still **does not match** any of:
  - `"我刚从洗车店出来"` (location declared)
  - `"我正在洗车"` (location declared)
  - `"我喜欢洗车"` (no movement intent)
  - `"We just got back from buying groceries"` (location declared,
    movement in the past)
- The reproduction input from the F-143 walkthrough now produces
  the `missing_subject` ambiguity (it was missed before) and the
  F-134 world count grows accordingly.
- The detector's wall-clock impact stays under 5 ms for inputs
  up to 200 characters.

## Acceptance Criteria

- `tests/logical_kanban/test_f147_movement_phrase_tolerance.py`
  covers the six positive cases and four negative cases listed
  above. Each is asserted at the
  `AmbiguityDetector.detect(...)` level, not the pattern-library
  level, so future pattern rewrites do not silently break
  coverage.
- A **non-reproduction-domain** input is part of the test matrix:
  `"我要去取快递"`, `"heading to the airport"`,
  `"我准备出发去办理签证"`. Each is asserted to produce a
  `missing_subject` ambiguity. This proves the fix is not
  car-wash-specific.
- The reproduction input from the F-143 walkthrough is encoded
  as a regression test: it produces at least one `Ambiguity` of
  kind `missing_subject` with `severity='major'`.
- `tests/logical_kanban/test_fuzzy_multiworld.py` continues to
  pass with the existing `P-INFO-001` cases intact.
- A snapshot of `AmbiguityReport.to_dict()` is captured for the
  reproduction input (post F-143, F-144, F-145, F-146, F-147)
  and committed to `tests/logical_kanban/snapshots/`. Any
  future change to the report shape must update the snapshot
  deliberately.

## Dependencies

- F-134 (Fuzzy Input and Multi-World Handling) — pattern library
  and detector.
- F-145 (Disambiguating Tokens as Confidence Boosters) — the
  reproduction input now produces both the widened
  `missing_subject` and the disambiguated `service_mode`
  ambiguity; F-147 composes with F-145, not regresses it.
- F-146 (Question-Context Suppression) — the post-window
  `还是` marker for the question-frame guard must coexist with
  the new colloquial variants. F-146's negative clause does not
  match `"出发去"` / `"前往"` / `"heading to"`, and F-147
  keeps it that way.

## Out of Scope

- A general-purpose Chinese verb-phrase extractor. The
  8-character window is a heuristic. Real NLP integration is a
  follow-up that depends on the F-143 LLM substrate (L1 fact
  pre-processor) and the team's NLP roadmap.
- Catching every movement construction. The MVP covers `去` plus
  colloquial variants; constructions like `飞往` (fly to),
  `赶往` (rush to), `前往…开会` (head to ... for a meeting)
  are addressed by the L3 fallback in F-143, not by F-147.
- Re-ordering the interpretation confidences. F-147 only widens
  the matcher; the existing `vehicle_at_home` /
  `vehicle_unknown` split and its 0.95 / 0.05 base confidences
  are unchanged.
- Distinguishing English from Chinese at the matcher level. The
  patterns are mixed-script by design; locale-specific patterns
  are a follow-up.
