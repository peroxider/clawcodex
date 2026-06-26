"""Facade — agent/fork_subagent.py has been moved to clawcodex_ext/agent/fork_subagent.

The fork-subagent machinery (``FORK_AGENT``, ``is_fork_subagent_enabled``,
``build_forked_messages``, ``build_worktree_notice``, ``is_in_fork_child``,
plus the ``FORK_*`` constants and tags) now lives in
:mod:`clawcodex_ext.agent.fork_subagent`. This module re-exports the
public surface so existing
``from src.agent.fork_subagent import ...`` callers keep working without
modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only covers 8
of 24 public names.
"""

import clawcodex_ext.agent.fork_subagent as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
