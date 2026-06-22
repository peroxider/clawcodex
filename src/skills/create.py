"""Facade — skills/create.py has been moved to clawcodex_ext/skills/create.

The F-88 skill creation helper now lives in
:mod:`clawcodex_ext.skills.create`. This module re-exports the
public surface so existing ``from src.skills.create import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.skills.create as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
