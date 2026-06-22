"""Facade — buddy/companion.py has been moved to clawcodex_ext/buddy/companion.

The F-88 companion roll/get state (``Roll``, ``SALT``,
``get_companion``, ``roll``, ``roll_with_seed``,
``companion_user_id``) now lives in
:mod:`clawcodex_ext.buddy.companion`. This module re-exports the
public surface so existing ``from src.buddy.companion import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 6 of 26 public names.
"""

import clawcodex_ext.buddy.companion as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
