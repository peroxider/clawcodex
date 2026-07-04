"""Facade — agent/resume_agent.py has been moved to clawcodex_ext/agent/resume_agent.

The auto-resume machinery for terminal local-agent tasks
(``resume_agent_background``, ``is_terminal_task_status``,
``TranscriptReader``, ``LocalAgentTaskState``, etc.) now lives in
:mod:`clawcodex_ext.agent.resume_agent`. This module re-exports the
public surface so existing
``from src.agent.resume_agent import ...`` callers keep working without
modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only covers 2
of 13 public names.
"""

import clawcodex_ext.agent.resume_agent as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
