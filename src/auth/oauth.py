"""Facade — auth/oauth.py has been moved to clawcodex_ext/auth/oauth.

The F-88 OAuth PKCE flow (``OAuthFlow``, ``OAuthTokens``,
``DEFAULT_AUTH_URL``, etc.) now lives in
:mod:`clawcodex_ext.auth.oauth`. This module re-exports the public
surface so existing ``from src.auth.oauth import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.auth.oauth as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
