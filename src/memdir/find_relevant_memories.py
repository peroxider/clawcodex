"""Facade — memdir/find_relevant_memories.py has been moved to clawcodex_ext/memdir/find_relevant_memories.

The F-88 relevant-memory finder (``MAX_RELEVANT_MEMORIES``,
``RelevantMemory``, ``find_relevant_memories``) now lives in
:mod:`clawcodex_ext.memdir.find_relevant_memories`. This module
re-exports the public surface so existing
``from src.memdir.find_relevant_memories import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 3 of 15 public names.
"""

import clawcodex_ext.memdir.find_relevant_memories as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
