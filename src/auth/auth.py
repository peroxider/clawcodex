"""Facade — auth/auth.py has been moved to clawcodex_ext/auth/auth.

The F-88 API key management (``ApiKeyInfo``, ``load_api_key``,
``validate_api_key``, ``get_api_key_source``) now lives in
:mod:`clawcodex_ext.auth.auth`. This module re-exports the public
surface so existing ``from src.auth.auth import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.auth.auth as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
