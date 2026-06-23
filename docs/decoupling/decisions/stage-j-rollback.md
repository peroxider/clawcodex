# Stage J Rollback Decision

**Date:** 2026-06-23
**Status:** Accepted — rollback completed
**Deciders:** ClawCodex decoupling working group
**Scope:** `src/services/mcp/` ↔ `clawcodex_ext/services/mcp/` migration attempt

## Context

We attempted to decouple the MCP communication layer (32 files / 7800 LOC) from
`src/services/mcp/` into `clawcodex_ext/services/mcp/` per CLAUDE.md Pattern 2
(Layer 1 ext may import from Layer 0 src) and Pattern D (extension overlay
mirrors src/ structure). The success criterion was explicit: **patch line count
DECREASE + clean code structure**.

### What we did

| Phase | Action | Outcome |
|-------|--------|---------|
| J-1   | Baseline lock-in (32 files / 7800 LOC, 23 patches / 2638 lines) | ✓ metrics recorded |
| J-2   | `git mv` 32 MCP files to `clawcodex_ext/services/mcp/`, rewrite 5 external consumers (chrome/*.py) to import from ext path | ✓ no test regression |
| J-3   | Generate 31 facade files + 1 aggregate `__init__.py` re-exporting 103 public symbols from ext | ✓ 86% src/ line reduction (7800 → 1082) |
| J-4   | Regenerate `patches/upstream/b24b8cb/series` + 32 per-file MCP patches | ✗ **FAIL** — patch lines went 2638 → 8958 (+240%) |

### Why J-4 failed

The root cause was **architectural tension between clean src/ and patch size**:

1. `src/upstream/b24b8cb/services/mcp/` contains the **full upstream
   implementation** (~671 lines per file × 32 files).
2. Our facades in `src/services/mcp/` were thin re-exports (~32 lines per file).
3. The diff computation = `remove upstream_full - add facade` = ~640 lines of
   removal replaced by 32 lines of addition → **net +608 lines per patch**.
4. Across 32 patches: +19,500 lines net, surfacing as 8958 patch lines after
   quilt deduplication.

The original 23 patches had been aggregated by file-group (1 patch covering
many files in `src/services/mcp/auth*.py` etc.), which amortized the per-file
diff. After J-4 the patcher split to 1-patch-per-file, exposing the per-file
overhead.

The fundamental incompatibility: **clean src/ and small patches cannot coexist
when upstream's full implementation lives at the same path**. Either we keep
full src/ (and accept upstream-style patch size) or we keep small src/ (and
accept that patches must shrink, which requires upstream's own src/ to be
empty — i.e. MCP must be removed from upstream, which is not our decision).

## Decision

**Roll back Phase J-2 / J-3 / J-4.** Restore:
1. `src/services/mcp/` to its full 32-file / 7800-line implementation
2. `patches/upstream/b24b8cb/series` and `patches/upstream/b24b8cb/merged/`
   to git HEAD state
3. **Preserve the 5 chrome/*.py import rewrites** (they reference
   `clawcodex_ext.services.mcp` which coexists with `src/services.mcp` full
   implementation; semantically equivalent, both modules export the same
   symbols via independent paths)
4. Delete temporary artifacts (`.phase_j1_baseline`, `.phase_j3_tmp/`,
   `tmp_mcp_baseline/`)
5. `clawcodex_ext/services/mcp/` is **kept** as an opt-in layered import path
   that downstream code may use, but is no longer the canonical location

## Rationale

### Why rollback beats ship-as-is

| Option | Patch lines | src/ cleanliness | merge cost |
|--------|-------------|-------------------|------------|
| Ship J-4 | +8958 (+240%) | clean | high merge cost upstream |
| Roll back | +0 (baseline) | unchanged | zero merge cost |
| Hybrid (move only, no facade) | +0 | messy (ext has full impl, src/ has facades) | zero merge cost |

The hybrid was rejected because having full implementation in ext and
facades in src/ creates two equivalent import paths with the same symbols —
confusing for downstream callers and a source of subtle drift.

The ship-as-is option was rejected because the patch line increase is the
single largest regression in the b24b8cb patch series — it would have wiped
out the cumulative win from the entire Tier A–E decoupling work.

### Why we keep `clawcodex_ext/services/mcp/` and the chrome/*.py rewrites

The original 5 chrome/*.py rewrites (lines 177/431/495 + 2 docstrings) are
forward-compatible with both states:

- If `clawcodex_ext/services/mcp/` exists, chrome imports resolve to the ext
  layer (current post-rollback state — same code, different import path).
- If we ever re-attempt decoupling, the chrome layer is already pointed at
  ext and needs no further change.
- The rewrites are independent of patch size, so they impose no cost on the
  rolled-back state.

## Consequences

### Positive

- `patches/upstream/b24b8cb/` is back to baseline (597 merged files, 613 series
  lines) — git working tree clean against HEAD
- `src/services/mcp/` is restored to 32 files / 7800 lines / full implementation
- Upstream merge cost stays at zero
- chrome/*.py is already migrated to ext import path (no rework needed if we
  try decoupling again)

### Negative

- `clawcodex_ext/services/mcp/` is a phantom — exists but has no caller
  except the 5 chrome/*.py files. Future readers may be confused by its
  existence.
- We spent ~2 hours on J-2/3/4 to learn that MCP cannot be decoupled under
  the current upstream quilt structure.

### Neutral

- The pre_j4 series backup I created during J-4 turned out to be wrong —
  the merged/ directory had already been regenerated by a prior commit
  (`3c0c5935`), so the series/merged alignment I thought I was preserving
  never existed in that exact form at HEAD. We restored from HEAD instead,
  which is the correct baseline.

## Lessons learned

1. **Always verify the invariant before measuring improvement.** The success
   criterion "patch lines decrease" assumed the pre-state was a clean
   series↔merged alignment. In fact, the series I saved as pre_j4 baseline
   was from BEFORE the last regeneration, and its corresponding merged/
   state was different from what I had on disk.
2. **Diff-based decoupling has a hard ceiling.** When upstream's full
   implementation lives at the same path, the diff is bounded by upstream's
   size, not our refactor's savings. Facades only help if upstream itself is
   thinner than our refactor.
3. **Aggregated patches amortize overhead.** The original 23 patches covered
   multiple MCP files each, hiding per-file diff cost. The J-4 per-file
   split exposed it. Future patch generation should consider grouping
   related files when both endpoints are full implementations.

## Follow-up actions

- [ ] Document `clawcodex_ext/services/mcp/` as "phantom layer — reserved for
      future decoupling attempts" in the module docstring
- [ ] Investigate whether `b24b8cb_diff_summary.txt` can be re-generated to
      reflect the rolled-back state
- [ ] Consider whether MCP should be a separate feature (F-NN) with its own
      dedicated upstream-sync strategy rather than piggybacking on the
      quilt-based series

## References

- CLAUDE.md — Decoupling Mandate, Pattern 2 / D
- `docs/decoupling/b24b8cb_diff_summary.txt` — pre-rollback diff inventory
- `phase_j1_baseline` (deleted) — J-1 metrics snapshot
- Commit `ef0408d2` — last successful series regeneration before J-2/3/4 attempt