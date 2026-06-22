"""Facade — skills/bundled_skills.py has been moved to clawcodex_ext/skills/bundled_skills.

The F-88 bundled skill registry (``BundledSkillDefinition``,
``register_bundled_skill``, etc.) now lives in
:mod:`clawcodex_ext.skills.bundled_skills`. This module re-exports
the public surface so existing
``from src.skills.bundled_skills import ...`` callers keep working
without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.skills.bundled_skills as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
