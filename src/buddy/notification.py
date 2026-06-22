"""Facade — buddy/notification.py has been moved to clawcodex_ext/buddy/notification.

The F-88 buddy notification helpers
(``find_buddy_trigger_positions``, ``is_buddy_live``,
``is_buddy_teaser_window``) now live in
:mod:`clawcodex_ext.buddy.notification`. This module re-exports the
public surface so existing ``from src.buddy.notification import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 3 of 7 public names.
"""

import clawcodex_ext.buddy.notification as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
