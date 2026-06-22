"""Facade — buddy/sprites.py has been moved to clawcodex_ext/buddy/sprites.

The F-88 buddy sprite renderer (``BODIES``, ``HAT_LINES``,
``MIN_COLS_FOR_FULL_SPRITE``, ``render_face``, ``render_sprite``,
``sprite_frame_count``) now lives in
:mod:`clawcodex_ext.buddy.sprites`. This module re-exports the
public surface so existing ``from src.buddy.sprites import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 6 of 11 public names.
"""

import clawcodex_ext.buddy.sprites as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
