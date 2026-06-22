"""Facade — memdir/team_mem_prompts.py has been moved to clawcodex_ext/memdir/team_mem_prompts.

The F-88 team-memory prompt builders (``DIRS_EXIST_GUIDANCE``,
``TYPES_SECTION_COMBINED``, ``build_combined_memory_prompt``) now
live in :mod:`clawcodex_ext.memdir.team_mem_prompts`. This module
re-exports the public surface so existing
``from src.memdir.team_mem_prompts import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 3 of 13 public names.
"""

import clawcodex_ext.memdir.team_mem_prompts as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
