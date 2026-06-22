"""Facade — agent/load_plugin_agents.py has been moved to clawcodex_ext/agent/load_plugin_agents.

The plugin-agent loader (``load_plugin_agents``, ``LoadedPlugin``) now
lives in :mod:`clawcodex_ext.agent.load_plugin_agents`. This module
re-exports the public surface so existing
``from src.agent.load_plugin_agents import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.load_plugin_agents as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
