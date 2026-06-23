"""Facade — memdir/team_mem_paths.py has been moved to clawcodex_ext/memdir/team_mem_paths.

The F-88 team-memory path helpers (``PathTraversalError``,
``get_team_mem_entrypoint``, ``get_team_mem_path``,
``is_team_mem_file``, ``is_team_mem_path``,
``is_team_memory_enabled``, ``validate_team_mem_key``,
``validate_team_mem_write_path``) now live in
:mod:`clawcodex_ext.memdir.team_mem_paths`. This module re-exports
the public surface so existing
``from src.memdir.team_mem_paths import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 8 of 15 public names.
"""

import clawcodex_ext.memdir.team_mem_paths as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)

# Explicitly re-export test helpers that are private (underscore-prefixed)
# in the implementation module but relied upon by downstream tests.
from clawcodex_ext.memdir.team_mem_paths import (  # noqa: F401,E402
    _realpath_deepest_existing,
    _sanitize_path_key,
)
