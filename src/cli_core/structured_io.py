"""Facade — cli_core/structured_io.py has been moved to clawcodex_ext/cli_core/structured_io.

The F-88 structured NDJSON I/O (``StreamJsonReader``,
``StreamJsonWriter``, ``HeadlessEvent`` and subclasses) now lives in
:mod:`clawcodex_ext.cli_core.structured_io`. This module re-exports
the public surface so existing
``from src.cli_core.structured_io import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.cli_core.structured_io as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
