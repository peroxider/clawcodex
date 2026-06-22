"""Facade — memdir/memory_age.py has been moved to clawcodex_ext/memdir/memory_age.

The F-88 memory-age helpers (``memory_age``, ``memory_age_days``,
``memory_freshness_note``, ``memory_freshness_text``) now live in
:mod:`clawcodex_ext.memdir.memory_age`. This module re-exports the
public surface so existing ``from src.memdir.memory_age import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 4 of 7 public names.
"""

import clawcodex_ext.memdir.memory_age as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
