"""Facade — buddy/feature.py has been moved to clawcodex_ext/buddy/feature.

The F-88 buddy feature flag (``is_buddy_enabled``) now lives in
:mod:`clawcodex_ext.buddy.feature`. This module re-exports the
public surface so existing ``from src.buddy.feature import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 1 of 2 public names.
"""

import clawcodex_ext.buddy.feature as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
