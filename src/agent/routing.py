"""Facade — agent/routing.py has been moved to clawcodex_ext/agent/routing.

The F-88 P88-C prompt-to-subagent-type classifier
(``classify_prompt_to_agent_type``, ``AGENT_TYPE_*`` constants) now
lives in :mod:`clawcodex_ext.agent.routing`. This module re-exports the
public surface so existing
``from src.agent.routing import ...`` callers keep working without
modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only covers
2 of 5 public names.
"""

import clawcodex_ext.agent.routing as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
