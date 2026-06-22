"""Facade — agent/run_agent.py has been moved to clawcodex_ext/agent/run_agent.

The agent-lifecycle machinery (``run_agent`` async generator,
``RunAgentParams`` / ``RunAgentResult`` dataclasses,
``resolve_permission_mode``, ``filter_incomplete_tool_calls``,
``SUBAGENT_DEFAULT_MAX_TURNS``) now lives in
:mod:`clawcodex_ext.agent.run_agent`. This module re-exports the public
surface so existing ``from src.agent.run_agent import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.run_agent as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
