"""Facade — agent/foreground_promotion.py has been moved to clawcodex_ext/agent/foreground_promotion.

The foreground→background agent promotion machinery
(``LocalAgentTaskState``, ``promote_to_background``, etc.) now lives in
:mod:`clawcodex_ext.agent.foreground_promotion`. This module re-exports
the public surface so existing
``from src.agent.foreground_promotion import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only covers 4
of 13 public names.
"""

import clawcodex_ext.agent.foreground_promotion as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
