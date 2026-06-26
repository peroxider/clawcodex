"""Facade — agent/session.py has been moved to clawcodex_ext/agent/session.

The ``Session`` class plus session-persistence and resume helpers now live
in :mod:`clawcodex_ext.agent.session`. This module re-exports the public
surface so existing ``from src.agent.session import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.session as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
