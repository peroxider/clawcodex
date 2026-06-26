"""Facade — agent/prompt.py has been moved to clawcodex_ext/agent/prompt.

The agent-tool prompt helpers (``get_agent_prompt``,
``get_agent_system_prompt``, ``format_agent_line``) now live in
:mod:`clawcodex_ext.agent.prompt`. This module re-exports the public
surface so existing ``from src.agent.prompt import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.prompt as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
