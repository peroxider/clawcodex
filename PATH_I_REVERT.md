# Path I Revert Post-Mortem

**Date**: 2026-06-24
**Branch**: dev-decoupling-refactor-b24b8cb
**Outcome**: Section (e) of `patches/upstream/b24b8cb/preserve.list` reverted.
Path I (sys.modules swap) is **rolled back**. Section (d) (Path H) remains
in effect. Net patch count returns from 266 → 471 (effective) once the
unpreserve is applied — see "Final state" below for the actual current
patch count.

## TL;DR

Section (e) was based on a **flawed facade-format assumption**: it
presumed the 205 `src/X.py` files in scope were star-import facades
(~150-200B delta). In reality all 205 are **full lazy-proxy facades**
(`def __getattr__(name): import clawcodex_ext.X as _mod; …`). The
src/X.py facade **already self-routes** to `clawcodex_ext.X` at runtime
— the `MetaPathFinder` swap mechanism was therefore both **redundant**
(no routing benefit) **and harmful** (it caused a re-load bug that
broke `tests/stability_gate/test_stage3d_runtime_commands.py`).

## The swap was redundant

Inspected facade pattern (e.g. `src/command_system/registry.py`):

```python
"""Facade — command_system/registry.py has been moved to clawcodex_ext (lazy proxy)."""

__all__ = ["CommandRegistry", "get_command_registry", …]

def __getattr__(name: str):
    import clawcodex_ext.command_system.registry as _mod
    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(...)
```

When code does `from src.command_system.registry import get_command_registry`,
Python's import machinery loads the facade, which calls `__getattr__`,
which imports `clawcodex_ext.command_system.registry` and returns its
attribute. No external swap needed — the routing is **inside** the
facade itself.

## The swap was harmful

The swap's `find_spec` pre-populated `sys.modules["src.command_system.registry"]`
with the `clawcodex_ext.command_system.registry` module object, then
returned a `ModuleSpec` with a `_NoopLoader`. The intent was that
Python would treat `src.command_system.registry` as a no-op alias for
`clawcodex_ext.command_system.registry`.

What actually happened during `register_runtime_commands(None)`:

1. Swap pre-populates `sys.modules["src.command_system.registry"] = ext_module`.
2. The facade's `def __getattr__` runs `import clawcodex_ext.command_system.registry as _mod`.
3. Python's import machinery processes the cached `clawcodex_ext.command_system.registry`
   entry but **re-executes its module body** because the spec returned by
   `_find_spec` for the freshly-imported `clawcodex_ext.command_system.registry`
   does not match the cached module's existing spec.
4. The re-execution produces a **new** module object with id X', replacing
   the original (id X) in `sys.modules`. The new module has its own
   `_REGISTRY = CommandRegistry()` singleton (id Y).
5. `src.command_system.registry` still points to the OLD module object
   (id X, registry Y). `clawcodex_ext.command_system.registry` now
   points to the NEW module object (id X', registry Y').
6. `register_runtime_commands(None)` registers `model`/`provider` into
   registry Y. The test then calls `get_command_registry()` (from
   `clawcodex_ext.command_system`, returns registry Y') — gets `None`.

Result: `tests/stability_gate/test_stage3d_runtime_commands.py::
TestRuntimeCommandsRegistration::test_register_runtime_commands_adds_model`
asserts `cmd is not None` → fails.

Reproduced in isolation, not state pollution, not import-order dependent.
Verified the same failure mode for both `_load_unlocked` paths in the
swapped module and the facade's lazy-proxy path.

## Why this slipped through earlier

Earlier verification claimed all 273 section (e) entries were working.
That was misleading — the test surface sampled didn't exercise the
facade's lazy proxy under the swap's pre-population. The Path H
section (d) entries don't have this bug because **their `src/X.py`
facades are loaded fresh from disk** (the preserve mechanism makes
src/X.py content == upstream content == clawcodex_ext/X.py, so they
share the same `_REGISTRY` regardless of how many times they're
loaded). Section (e) breaks because clawcodex_ext/X.py != upstream,
so each re-load creates a NEW module instance with a NEW singleton.

## Final state

- `patches/upstream/b24b8cb/preserve.list`: section (e) removed,
  replaced with a comment explaining why. Section (d) unchanged
  (42 entries).
- `clawcodex_ext/_facade_swap.py`, `clawcodex_ext/_facade_swap_paths.py`:
  deleted.
- `clawcodex_ext/__init__.py`: swap installer removed.
- `patches/upstream/b24b8cb/merged/`: 266 patches (was 471 after Path H).
- Full stability gate: 327 passed, 0 failures.
- `tests/stability_gate/test_stage3d_runtime_commands.py`:
  `test_register_runtime_commands_adds_model` PASSES.

## Lesson

A `MetaPathFinder` that pre-populates `sys.modules` for an already-imported
module is **incompatible** with Python's "cached module is valid as long as
its spec matches" invariant. When the underlying ext module is later
re-imported by other code (e.g. the facade's `__getattr__` doing
`import clawcodex_ext.X as _mod`), Python sees a spec mismatch and
re-executes the module body, producing a phantom duplicate. Always
return `ext_module.__spec__` (or a `_replace`'d copy) — never a fresh
`ModuleSpec(fullname, _NoopLoader(), …)` for a module that another
spec is also pointing at.

For downstream ClawCodex, the facade-only fork delta path is best
served by the existing **lazy-proxy `__getattr__`** pattern (section d).
Path I's sys.modules swap was a net negative and is no longer pursued.