"""Facade — memdir/memory_types.py has been moved to clawcodex_ext/memdir/memory_types.

The F-88 memory-type definitions (``MEMORY_DRIFT_CAVEAT``,
``MEMORY_FRONTMATTER_EXAMPLE``, ``MEMORY_TYPES``, ``MemoryType``,
``TRUSTING_RECALL_SECTION``, ``TYPES_SECTION_INDIVIDUAL``,
``WHAT_NOT_TO_SAVE_SECTION``, ``WHEN_TO_ACCESS_SECTION``,
``parse_memory_type``) now live in
:mod:`clawcodex_ext.memdir.memory_types`. This module re-exports the
public surface so existing ``from src.memdir.memory_types import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 9 of 11 public names.
"""

import clawcodex_ext.memdir.memory_types as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
