"""Facade — buddy/soul.py has been moved to clawcodex_ext/buddy/soul.

The F-88 buddy soul generators (``NAME_PREFIXES``, ``NAME_SUFFIXES``,
``PERSONALITIES``, ``create_stored_companion``) now live in
:mod:`clawcodex_ext.buddy.soul`. This module re-exports the public
surface so existing ``from src.buddy.soul import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 4 of 8 public names.
"""

import clawcodex_ext.buddy.soul as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
