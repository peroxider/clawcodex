"""Facade — buddy/observer.py has been moved to clawcodex_ext/buddy/observer.

The F-88 buddy observer (``fire_companion_observer``) now lives in
:mod:`clawcodex_ext.buddy.observer`. This module re-exports the
public surface so existing ``from src.buddy.observer import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 1 of 8 public names.
"""

import clawcodex_ext.buddy.observer as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
