"""Facade — agent/filter_agents_by_mcp.py has been moved to clawcodex_ext/agent/filter_agents_by_mcp.

The MCP-requirements filter (``filter_agents_by_mcp_requirements``,
``has_required_mcp_servers``) now lives in
:mod:`clawcodex_ext.agent.filter_agents_by_mcp`. This module re-exports
the public surface so existing
``from src.agent.filter_agents_by_mcp import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.filter_agents_by_mcp as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
