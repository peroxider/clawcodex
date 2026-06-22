"""Facade — skills/model.py has been moved to clawcodex_ext/skills/model.

The F-88 skill data model (Skill dataclass and related types) now
lives in :mod:`clawcodex_ext.skills.model`. This module re-exports
the public surface so existing ``from src.skills.model import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.skills.model as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
