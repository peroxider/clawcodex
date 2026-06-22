"""Facade — buddy/prompt.py has been moved to clawcodex_ext/buddy/prompt.

The F-88 buddy prompt helpers
(``build_companion_intro_attachment``, ``companion_intro_text``,
``format_companion_intro_attachments``) now live in
:mod:`clawcodex_ext.buddy.prompt`. This module re-exports the
public surface so existing ``from src.buddy.prompt import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 3 of 10 public names.
"""

import clawcodex_ext.buddy.prompt as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
