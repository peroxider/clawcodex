"""Facade — skills/loader.py has been moved to clawcodex_ext/skills/loader.

The F-88 skill loader (skill discovery, parsing, caching) now lives
in :mod:`clawcodex_ext.skills.loader`. This module re-exports the
public surface so existing ``from src.skills.loader import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module has no ``__all__``.
"""

import clawcodex_ext.skills.loader as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)

# Explicitly re-export the internal helpers that downstream tests rely on.
# These are underscore-prefixed (private by convention) but are imported
# by existing test suites that need to validate internal logic.
from clawcodex_ext.skills.loader import (  # noqa: F401,E402
    _coerce_allowed_tools,
    _coerce_description,
    _coerce_effort,
    _coerce_hooks,
    _coerce_model,
    _coerce_shell,
    _compile_path_spec,
    _dedup_by_realpath,
    _extract_description_from_markdown,
    _get_additional_skill_dirs,
    _get_file_identity,
    _is_bare_mode,
    _is_path_gitignored,
    _is_restricted_to_plugin_only,
    _is_skills_policy_disabled,
    _path_matches_pattern,
)
