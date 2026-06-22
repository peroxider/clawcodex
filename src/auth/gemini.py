"""Facade — auth/gemini.py has been moved to clawcodex_ext/auth/gemini.

The F-88 Gemini authentication (``GeminiAuth``) now lives in
:mod:`clawcodex_ext.auth.gemini`. This module re-exports the public
surface so existing ``from src.auth.gemini import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.auth.gemini as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
