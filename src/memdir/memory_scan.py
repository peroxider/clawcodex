"""Facade — memdir/memory_scan.py has been moved to clawcodex_ext/memdir/memory_scan.

The F-88 memory-file scanner (``FRONTMATTER_MAX_LINES``, ``MAX_DEPTH``,
``MAX_MEMORY_FILES``, ``MemoryHeader``, ``format_memory_manifest``,
``scan_memory_files``) now lives in
:mod:`clawcodex_ext.memdir.memory_scan`. This module re-exports the
public surface so existing ``from src.memdir.memory_scan import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 6 of 18 public names.
"""

import clawcodex_ext.memdir.memory_scan as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
