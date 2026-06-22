"""Facade — memdir/paths.py has been moved to clawcodex_ext/memdir/paths.

The F-88 memory path helpers (``find_canonical_git_root``,
``get_auto_mem_daily_log_path``, ``get_auto_mem_entrypoint``,
``get_auto_mem_path``, ``get_memory_base_dir``,
``has_auto_mem_path_override``, ``is_auto_mem_path``,
``is_auto_memory_enabled``, ``sanitize_path``) now live in
:mod:`clawcodex_ext.memdir.paths`. This module re-exports the
public surface so existing ``from src.memdir.paths import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 9 of 16 public names.
"""

import clawcodex_ext.memdir.paths as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
