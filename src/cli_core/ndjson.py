"""Facade — cli_core/ndjson.py has been moved to clawcodex_ext/cli_core/ndjson.

The F-88 NDJSON helpers (``ndjson_safe_dumps``) now live in
:mod:`clawcodex_ext.cli_core.ndjson`. This module re-exports the public
surface so existing ``from src.cli_core.ndjson import ...`` callers
keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.cli_core.ndjson as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
