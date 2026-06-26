"""Facade — agent/parse_agent_markdown.py has been moved to clawcodex_ext/agent/parse_agent_markdown.

The ``parse_agent_from_markdown`` parser and related markdown-discovery
helpers now live in :mod:`clawcodex_ext.agent.parse_agent_markdown`. This
module re-exports the public surface so existing
``from src.agent.parse_agent_markdown import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.parse_agent_markdown as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
