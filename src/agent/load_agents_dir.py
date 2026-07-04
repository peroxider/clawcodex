"""Facade — agent/load_agents_dir.py has been moved to clawcodex_ext/agent/load_agents_dir.

The custom-agent discovery machinery
(``get_agent_definitions_with_overrides``,
``get_active_agents_from_list``,
``clear_agent_definitions_cache``, plus the ``SOURCE_*`` constants) now
lives in :mod:`clawcodex_ext.agent.load_agents_dir`. This module
re-exports the public surface so existing
``from src.agent.load_agents_dir import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.load_agents_dir as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
