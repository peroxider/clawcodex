"""Facade — skills/mcp_skill_builders.py has been moved to clawcodex_ext/skills/mcp_skill_builders.

The F-88 MCP skill builders now live in
:mod:`clawcodex_ext.skills.mcp_skill_builders`. This module
re-exports the public surface so existing
``from src.skills.mcp_skill_builders import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.skills.mcp_skill_builders as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
