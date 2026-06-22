"""Facade — agent/subagent_context.py has been moved to clawcodex_ext/agent/subagent_context.

The ``SubagentContextOverrides`` dataclass and ``create_subagent_context``
factory now live in :mod:`clawcodex_ext.agent.subagent_context`. This
module re-exports the public surface so existing
``from src.agent.subagent_context import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.subagent_context as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
