"""Facade — buddy/types.py has been moved to clawcodex_ext/buddy/types.

The F-88 buddy type hierarchy (``Companion``, ``CompanionBones``,
``CompanionSoul``, ``EYES``, ``Eye``, ``HATS``, ``Hat``,
``RARITIES``, ``RARITY_COLORS``, ``RARITY_STARS``,
``RARITY_WEIGHTS``, ``Rarity``, ``SPECIES``, ``STAT_NAMES``,
``Species``, ``StatName``, ``StoredCompanion``) now lives in
:mod:`clawcodex_ext.buddy.types`. This module re-exports the
public surface so existing ``from src.buddy.types import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 17 of 21 public names.
"""

import clawcodex_ext.buddy.types as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
