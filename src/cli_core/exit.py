"""Facade — cli_core/exit.py has been moved to clawcodex_ext/cli_core/exit.

The F-88 CLI exit helpers (``cli_error``, ``cli_ok``) now live in
:mod:`clawcodex_ext.cli_core.exit`. This module re-exports the public
surface so existing ``from src.cli_core.exit import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.cli_core.exit as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
