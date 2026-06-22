"""Facade — auth/claude_ai.py has been moved to clawcodex_ext/auth/claude_ai.

The F-88 claude.ai OAuth token + entitlement helpers
(``get_claude_ai_oauth_tokens``, ``is_claude_ai_subscriber``,
``has_profile_scope``, etc.) now live in
:mod:`clawcodex_ext.auth.claude_ai`. This module re-exports the public
surface so existing ``from src.auth.claude_ai import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only covers
14 of 21 public names.
"""

import clawcodex_ext.auth.claude_ai as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
