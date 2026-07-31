# F-57 Phase 5 Session Macro MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **Revision:** 2026-07-23 v2 — incorporates second review (task order, unified resolver, snapshot COW, session cleanup, ValidatedSessionMacro, TOCTOU, REPL+registration bootstrap, expanded tests, git hygiene).
> **Status:** ✅ Completed. Implementation and acceptance matrix re-verified on 2026-07-31 (`90 passed, 21 subtests passed`).

**Goal:** Register a complete MacroDefinition into a per-session immutable overlay (after a dedicated confirm gate) so the macro is immediately searchable and callable on **all** lookup paths—without mutating the shared `ToolRegistry`.

**Architecture:** `ToolContext.session_macro_overlay` holds an immutable `SessionMacroSnapshot`. All tool lookups go through `resolve_tool_for_context` (overlay > base). Registration: capability gate → strict parse → validate → `ValidatedSessionMacro` → plan → confirm → locked TOCTOU → COW snapshot commit → provenance-aware `options.tools` sync. Session-id change runs full cleanup (overlay + options + retrieval state + rate window), restoring any covered base tools by object identity.

**Tech Stack:** Python 3, existing macros / workflow / ToolContext stack, unittest/pytest.

**Design spec:** `D:\笔记\clawcodex\F-57-Phase5-Session-Macro-MVP-设计方案.md`（v2）

## Global Constraints

- `ToolContext` is `@dataclass(slots=True)` — **declare all new fields before any test constructs a real context with overlay/confirm/allow**.
- Do **not** `ToolRegistry.register` / `unregister` session macros.
- Single lookup API: `resolve_tool_for_context(context, name, *, base_registry=None) -> Tool | None`. Wire: `tool_execution.run_tool_use`, `ToolRegistry.dispatch`, `execute._resolve_target`, ToolSearch activate/preflight.
- `definition.name` must match `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`; never silent kebabize; `target_tool` must equal `name` or be empty then set to `name`; mismatch → error.
- Reject `selection=exclusive` for session (`macro_selection_forbidden`); do not silently downgrade.
- Forbid workflow/session macros as steps; direct steps ≤ 16.
- `validate_session_macro_definition` returns **`ValidatedSessionMacro(definition, workflow, tool_spec)`**, not bare `CompositeWorkflowSpec`.
- Strict session parsers — **do not** reuse `loader.parse_macro_route` (it silently coerces enums).
- `tool_index` = current bundle/agent allowlist ∪ explicit base tools ∪ non-session names already on `options.tools` — **not** the full global registry.
- `allow_session_macro_registration` is a **universal capability gate** (check first). Main TUI/REPL set `True`; subagent/headless default `False`.
- Confirm ignores bypass / don't-ask-again; callback exception = deny; interactivity via `options.is_non_interactive_session`.
- Confirm does not grant step permissions.
- Overlay = immutable snapshot + COW under lock; readers use `overlay.read()` only.
- Session switch cleanup must strip overlay-provenance Tools from `options.tools` / `retrieval_hidden_tools`, clear retrieval plan/suppressed if needed, reset rate window, **restore covered base Tools by identity**.
- Protected verified builtin exclusive targets → `macro_route_conflict` (validate + TOCTOU).
- **Git:** use a clean worktree or `git add -p` / path-limited staging. Do **not** `git add` whole dirty files that already contain unrelated WIP (`factory.py`, `catalog.py`, F-57 docs, etc.).

---

## File map

| File | Responsibility |
|------|----------------|
| Modify: `clawcodex_ext/tool_system/context.py` | Declare `session_macro_overlay`, `confirm_session_macro_plan`, `allow_session_macro_registration`; helpers to sync/clean tools |
| Create: `extensions/sop_converter/macros/resolve_tool.py` | `resolve_tool_for_context` |
| Create: `extensions/sop_converter/macros/session.py` | Snapshot/Overlay, cleanup, register, `iter_effective_tools`, `sync_effective_tools` |
| Create: `extensions/sop_converter/macros/session_parse.py` | Strict parse for session definitions/routes |
| Modify: `extensions/sop_converter/macros/validation.py` | `validate_macro_core` + policies; `ValidatedSessionMacro` |
| Modify: `extensions/sop_converter/macros/catalog.py` | `resolve_macro` reads snapshot |
| Modify: `clawcodex_ext/services/tool_execution/tool_execution.py` | Use resolver |
| Modify: `clawcodex_ext/tool_system/registry.py` | `dispatch` uses resolver |
| Modify: `clawcodex_ext/tool_system/tools/execute.py` | `_resolve_target` uses resolver |
| Modify: `clawcodex_ext/tool_system/tools/tool_search.py` | activate/preflight + session routes from overlay |
| Modify: `clawcodex_ext/query/query.py` | effective tools merge |
| Modify: `extensions/sop_converter/bundle_context.py` | re-append session tools after filter |
| Modify: `clawcodex_ext/agent/subagent_context.py` | share overlay; allow=False; confirm=None |
| Modify: `extensions/tool_system_ext/registration.py` | append `register-macro-workflow` Tool |
| Create: `extensions/sop_converter/macros/register_tool.py` | Tool implementation |
| Modify: `clawcodex_ext/tui/agent_bridge.py` | allow=True + confirm UI |
| Modify: `clawcodex_ext/repl/core.py` | allow=True + confirm UI (same contract) |
| Create: `tests/misc/test_sop_session_macros.py` | Acceptance |
| Modify: F-57 feature doc §0/§7 when done | Status sync |

---

### Task 1: ToolContext fields + strict parse + ValidatedSessionMacro

**Files:**
- Modify: `clawcodex_ext/tool_system/context.py`
- Create: `extensions/sop_converter/macros/session_parse.py`
- Modify: `extensions/sop_converter/macros/validation.py`
- Create: `tests/misc/test_sop_session_macros.py`
- Keep green: `tests/misc/test_sop_macro_convert_phase4.py`

**Interfaces:**
- Produces:
  - `ToolContext.session_macro_overlay: Any | None = None`
  - `ToolContext.confirm_session_macro_plan: Callable | None = None`
  - `ToolContext.allow_session_macro_registration: bool = False`
  - `parse_session_macro_definition(data: dict) -> MacroDefinition` (strict)
  - `ValidatedSessionMacro(definition, workflow, tool_spec)`
  - `validate_session_macro_definition(...) -> ValidatedSessionMacro`
  - `validate_macro_core(...)` used by bundle + session
- Consumes: existing `workflow_dict_to_spec`, `MacroConvertError`, `AgentToolSpec`

- [x] **Step 1: Add ToolContext fields (slots-safe)**

Add the three fields with defaults to `ToolContext` so later tasks can construct real contexts.

- [x] **Step 2: Write failing validation/parse tests**

Cover: non-kebab name; exclusive rejected; target mismatch; unknown field; illegal selection enum (strict, not coerced); workflow callable forbidden; returns `ValidatedSessionMacro` with normalized `definition.routing.target_tool == name`.

- [x] **Step 3: Implement strict parse + validation split**

- `parse_session_macro_route`: invalid enum → `MacroConvertError` (no silent default).  
- Bundle `validate_macro_definition` keeps Phase 4 exclusive→prefer downgrade.  
- Session path rejects exclusive; builds `AgentToolSpec(call_type="workflow", call_impl={"catalog_id": f"session:{name}"}, ...)`.  
- `tool_index` parameter documented as allowlist-shaped; tests pass a small allowlist only.

- [x] **Step 4: Run**

```bash
pytest tests/misc/test_sop_session_macros.py -k "parse or Validat or name or exclusive or target" -v
pytest tests/misc/test_sop_macro_convert_phase4.py -v
```

- [x] **Step 5: Commit (path-limited)**

```bash
git add clawcodex_ext/tool_system/context.py \
  extensions/sop_converter/macros/session_parse.py \
  extensions/sop_converter/macros/validation.py \
  tests/misc/test_sop_session_macros.py
git commit -m "feat(f57): session macro parse/validate and ToolContext fields"
```

---

### Task 2: `resolve_tool_for_context` + immutable overlay snapshot

**Files:**
- Create: `extensions/sop_converter/macros/resolve_tool.py`
- Create: `extensions/sop_converter/macros/session.py` (snapshot/overlay types + read/commit only)
- Test: `tests/misc/test_sop_session_macros.py`

**Interfaces:**
- Produces:
  - `SessionMacroSnapshot` (frozen), `SessionMacroOverlay` (lock + COW commit)
  - `mark_session_macro_tool(tool) -> Tool` / `is_session_macro_tool(tool) -> bool`
  - `resolve_tool_for_context(context, name, *, base_registry=None) -> Tool | None`
- Consumes: ToolContext fields from Task 1

- [x] **Step 1: Failing tests**

```python
def test_resolver_prefers_overlay_over_registry_and_options(): ...
def test_snapshot_cow_replace_is_atomic(): ...
def test_resolver_ignores_overlay_when_owner_session_mismatches(): ...
```

- [x] **Step 2: Implement snapshot + resolver**

Resolver order:

1. `clear`/bind check: if overlay snapshot owner ≠ `context.session_id`, treat as no overlay (caller may also run full cleanup — Task 3).  
2. Lookup `snapshot.tools[name]` (case policy consistent with registry: lower-key map).  
3. Else `base_registry.get(name)` if provided.  
4. Else `find_tool_by_name(context.options.tools, name)` **skipping** stale session-provenance tools if owner mismatch.

- [x] **Step 3: Tests PASS + commit**

```bash
git add extensions/sop_converter/macros/resolve_tool.py extensions/sop_converter/macros/session.py tests/misc/test_sop_session_macros.py
git commit -m "feat(f57): immutable session overlay snapshot and resolve_tool_for_context"
```

---

### Task 3: Session-switch cleanup + effective tool pool merge

**Files:**
- Modify: `extensions/sop_converter/macros/session.py`
- Modify: `clawcodex_ext/tool_system/context.py` (optional thin wrappers)
- Modify: `clawcodex_ext/query/query.py`
- Modify: `extensions/sop_converter/bundle_context.py`
- Test: `tests/misc/test_sop_session_macros.py`

**Interfaces:**
- Produces:
  - `clear_session_macros_for_context(context) -> None`
  - `iter_effective_tools(context, base_tools) -> list[Tool]`
  - `sync_effective_tools(context) -> None`
- Consumes: provenance markers, `covered_base_tools` on snapshot

- [x] **Step 1: Failing tests**

```python
def test_session_switch_removes_overlay_tools_from_options_but_restores_covered_base(): ...
def test_session_switch_clears_retrieval_hidden_and_plan(): ...
def test_restore_retrieval_tools_does_not_revive_foreign_session_macros(): ...
def test_bundle_filter_keeps_session_macros(): ...
```

- [x] **Step 2: Implement cleanup**

`clear_session_macros_for_context`:

1. Read old snapshot (if any).  
2. Commit `None` / empty overlay.  
3. Filter `options.tools`: drop `is_session_macro_tool`; for each dropped name, if `covered_base_tools` had an entry, append that exact object back.  
4. Same filter on `retrieval_hidden_tools`.  
5. Clear `retrieval_plan`, `retrieval_suppressed_tools` if they reference removed macro names (safe default: clear plan entirely on session change).  
6. Rate window lives only in snapshot → discarded with it.

Hook: whenever `session_id` is assigned/changed in TUI resume / REPL session bind, call cleanup (Task 6 also wires call sites).

- [x] **Step 3: Wire `_resolve_effective_tools` to `iter_effective_tools`**

- [x] **Step 4: Tests PASS + commit**

```bash
git commit -m "feat(f57): provenance-aware session macro cleanup and tool pool merge"
```

---

### Task 4: register → plan → confirm → locked TOCTOU recommit

**Files:**
- Modify: `extensions/sop_converter/macros/session.py`
- Test: `tests/misc/test_sop_session_macros.py`

**Interfaces:**
- Produces: `SessionMacroPlan`, `register_session_macro(context, definition_dict, *, replace, tool_index, workflow_tool_names, protected_builtin_exclusive_targets, create_tool) -> dict`
- Consumes: `ValidatedSessionMacro`, confirm callback, allow flag

- [x] **Step 1: Failing tests**

```python
def test_capability_gate_blocks_even_when_interactive_confirm_would_pass(): ...
def test_confirm_false_writes_nothing(): ...
def test_confirm_exception_writes_nothing(): ...
def test_session_id_changes_during_confirm_aborts(): ...
def test_create_tool_failure_no_partial_commit(): ...
def test_rate_limit_and_macro_count_and_size_limits(): ...
def test_protected_builtin_exclusive_target_conflict(): ...
def test_concurrent_replace_uses_generation_check(): ...  # threading or sequential simulated TOCTOU
```

- [x] **Step 2: Implement register_session_macro**

Order (mandatory):

1. If not `context.allow_session_macro_registration` → `macro_capability_denied`.  
2. Require `session_id`.  
3. Strict parse + size limits.  
4. `validate_session_macro_definition(...) -> ValidatedSessionMacro`.  
5. Check protected builtin exclusive targets.  
6. Build frozen plan (steps: id, tool, args_template).  
7. Non-interactive: still requires allow=True **and** confirm callback (tests inject auto-approve).  
8. If confirm is None → deny.  
9. Call confirm; exception/False → deny.  
10. Lock: re-check session_id, owner, generation/exists/replace, limits, rate, protected targets, optionally re-validate allowlist set; `tool = create_tool(validated.tool_spec)` inside lock **before** commit; on failure abort.  
11. Build new `SessionMacroSnapshot` (copy maps, generation+1, record covered base tool if name existed in options/registry).  
12. `overlay.commit(new_snap)`.  
13. `sync_effective_tools(context)`.  
14. Return success JSON from **validated.definition**, not raw input.

- [x] **Step 3: Tests PASS + commit**

```bash
git commit -m "feat(f57): session macro register with confirm and TOCTOU snapshot commit"
```

---

### Task 5: Wire all call paths (execution, workflow, Execute, ToolSearch, subagent)

**Files:**
- Modify: `clawcodex_ext/services/tool_execution/tool_execution.py`
- Modify: `clawcodex_ext/tool_system/registry.py`
- Modify: `clawcodex_ext/tool_system/tools/execute.py`
- Modify: `clawcodex_ext/tool_system/tools/tool_search.py`
- Modify: `clawcodex_ext/agent/tool_authoring/factory.py` (pass overlay into `resolve_macro` only; avoid unrelated hunks)
- Modify: `clawcodex_ext/agent/subagent_context.py`
- Modify: `extensions/sop_converter/macros/catalog.py`
- Test: `tests/misc/test_sop_session_macros.py`, extend `tests/tool/test_tool_search_macro_routes.py` if needed

- [x] **Step 1: Failing tests per path**

```python
def test_main_tool_execution_uses_overlay_macro(): ...
def test_execute_tool_resolves_overlay_not_stale_base(): ...
def test_registry_dispatch_uses_resolver(): ...
def test_tool_search_preflight_and_activate_see_overlay_macro(): ...
def test_workflow_resolve_macro_from_snapshot(): ...
def test_subagent_can_dispatch_but_cannot_register(): ...
```

- [x] **Step 2: Replace lookups with `resolve_tool_for_context`**

- `tool_execution.py`: replace `find_tool_by_name(options.tools, ...)` primary lookup.  
- `registry.dispatch`: resolve via helper (pass `self` as base_registry).  
- `execute._resolve_target`: resolver first.  
- ToolSearch `_preflight_macro` / `_activate_toolsearch_matches`: use resolver; when activating session macro, `sync` into `options.tools` without `registry.register`.  
- `_load_macro_route_catalog`: read `overlay.read().routes`.  
- `resolve_macro`: if `catalog_id.startswith("session:")`, load from snapshot.  
- `subagent_context`: copy `session_macro_overlay`; set `allow_session_macro_registration=False`, `confirm_session_macro_plan=None`.

- [x] **Step 3: Run focused suites + commit (hunk-careful on factory/catalog)**

```bash
pytest tests/misc/test_sop_session_macros.py tests/tool/test_tool_search_macro_routes.py -v
git add -p clawcodex_ext/agent/tool_authoring/factory.py  # only overlay resolve hunks
git commit -m "feat(f57): unify session macro resolution across execution paths"
```

---

### Task 6: Bootstrap tool + TUI + REPL + headless

**Files:**
- Create: `extensions/sop_converter/macros/register_tool.py`
- Modify: `extensions/tool_system_ext/registration.py` — `EXTENSION_TOOLS.append(RegisterMacroWorkflowTool)`
- Modify: `clawcodex_ext/tui/agent_bridge.py`
- Modify: `clawcodex_ext/repl/core.py` (after ToolContext construction ~L781)
- Headless: ensure allow stays False by default (`clawcodex_ext/entrypoints/headless.py`)
- TUI resume (`tui/app.py` `_on_session_selected`): call `clear_session_macros_for_context` after session swap
- Test: confirm formatter unit tests; register tool e2e with injected confirm

- [x] **Step 1: Implement `register-macro-workflow` Tool** calling `register_session_macro`; build `tool_index` from active bundle allowlist + base tool names helper.

- [x] **Step 2: Register in `extensions/tool_system_ext/registration.py`**

- [x] **Step 3: Shared confirm helper** `format_session_macro_plan_for_ui(plan) -> str`; wire TUI modal **and** REPL ask path; both set `allow_session_macro_registration=True` and assign confirm callback. Confirm path must not update normal permission “don't ask again” rules.

- [x] **Step 4: Tests**

```python
def test_register_tool_requires_capability(): ...
def test_tui_and_repl_confirm_helpers_render_step_args(): ...
```

- [x] **Step 5: Commit**

```bash
git commit -m "feat(f57): register-macro-workflow tool with TUI/REPL confirm wiring"
```

---

### Task 7: Full acceptance matrix + docs + git hygiene check

**Files:**
- Expand tests
- Modify: `docs/feature_plan/04-architecture-sdk/f-57-sop-executable-composite-workflows.md` (§0 / §7 MVP status only)
- Sync notes design status if needed

- [x] **Step 1: Ensure matrix covered**

| Case | Expect |
|------|--------|
| Session switch → old options.tools macro not callable | pass |
| Session changes during confirm | `macro_stale_session` / deny; no write |
| Concurrent create/replace generation | one wins; other `macro_concurrent_modification` or retry deny |
| Main query path + Execute path same overlay tool | pass |
| Name collision with base tool; cleanup restores base object | pass |
| 32 macros / 64KiB / string caps | errors |
| create_tool raises | no snapshot commit |
| Subagent real dispatch of parent macro | pass |
| Subagent register | capability denied |
| Protected builtin exclusive clash | `macro_route_conflict` |
| bypassPermissions without confirm | deny |
| Phase 4 convert suite | still green |

- [x] **Step 2: Run broader regression**

```bash
pytest tests/misc/test_sop_session_macros.py \
  tests/misc/test_sop_macro_convert_phase4.py \
  tests/tool/test_tool_search_macro_routes.py \
  tests/tool/test_tool_search_layered_retrieval.py \
  tests/misc/test_sop_composite_runtime.py -v
```

- [x] **Step 3: Update F-57 §0/§7** — Phase 5 MVP wired; compiler/promote/trace still out.

- [x] **Step 4: Commit docs + tests only via path-limited add**

```bash
git add tests/misc/test_sop_session_macros.py \
  docs/feature_plan/04-architecture-sdk/f-57-sop-executable-composite-workflows.md \
  docs/superpowers/plans/2026-07-23-f57-phase5-session-macro-mvp.md
git commit -m "test(f57): session macro MVP acceptance; document Phase 5 MVP status"
```

---

## Self-review (plan vs design v2)

| Design requirement | Task |
|--------------------|------|
| ToolContext fields before overlay tests | T1 |
| Strict parse + ValidatedSessionMacro | T1 |
| Immutable snapshot + resolver | T2 |
| Provenance cleanup + tool pool | T3 |
| Confirm + TOCTOU + capability gate | T4 |
| All call paths + subagent | T5 |
| registration.py + TUI + REPL | T6 |
| Expanded matrix + docs + git hygiene | T7 |
| Protected builtin exclusive | T4 (+ T7) |
| allowlist-shaped tool_index | T1/T4/T6 |

---

## Analysis note (why v1 was not executable)

1. Task order used undeclared `slots` fields.  
2. Only patching `dispatch` left Execute / main execution / ToolSearch divergent.  
3. Syncing `options.tools` without provenance-aware cleanup leaked macros across sessions and broke base-tool restore.  
4. Returning only `CompositeWorkflowSpec` dropped normalized definition authority; loose `parse_macro_route` violated strict enums.  
5. Recommit missed session/generation/allowlist TOCTOU; multi-dict assign was not atomic.  
6. REPL + `registration.py` + capability semantics were underspecified.  
7. Suite/git instructions were too narrow / unsafe on a dirty tree.

---

## Execution handoff

Updated files:

- `D:\笔记\clawcodex\F-57-Phase5-Session-Macro-MVP-设计方案.md` (v2)
- `D:\笔记\clawcodex\F-57-Phase5-Session-Macro-MVP-implementation-plan.md` (v2)
- `docs/superpowers/plans/2026-07-23-f57-phase5-session-macro-mvp.md` (v2 sync)

**Two execution options:**

1. **Subagent-Driven (recommended)** — clean worktree per agent if possible  
2. **Inline Execution** — this session, path-limited commits only  

Which approach?
