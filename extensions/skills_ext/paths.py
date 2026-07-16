from __future__ import annotations

"""Compatibility projections of the canonical skill discovery paths.

These helpers do not discover or cache skills. They expose the path layout used
by clawcodex_ext.skills.loader for integrations that still import
extensions.skills_ext.paths.
"""

import os
from pathlib import Path

from clawcodex_ext.skills import loader as canonical_loader


def _get_global_config_dir() -> Path:
    """Return the canonical Claude user configuration directory."""

    return canonical_loader._get_global_config_dir()


def _get_managed_file_path() -> Path:
    """Return the canonical managed configuration directory."""

    return canonical_loader._get_managed_file_path()


def get_clawcodex_skills_dir() -> Path:
    """Return the legacy ClawCodex user skill directory."""

    return Path.home() / ".clawcodex" / "skills"


def get_clawcodex_managed_skills_dir() -> Path | None:
    """Return the optional ClawCodex managed override directory."""

    value = os.environ.get("CLAWCODEX_MANAGED_SKILLS_DIR")
    return Path(value).expanduser().resolve() if value else None


def get_clawcodex_user_skills_dirs() -> list[Path]:
    """Return ClawCodex-specific user roots used by the canonical loader."""

    roots = canonical_loader._legacy_user_skill_dirs(None)
    clawcodex_roots = {get_clawcodex_skills_dir().expanduser().resolve()}
    env_root = os.environ.get("CLAWCODEX_SKILLS_DIR")
    if env_root:
        clawcodex_roots.add(Path(env_root).expanduser().resolve())
    return [root for root in roots if root in clawcodex_roots]


def get_clawcodex_project_skills_dir(
    project_root: str | Path | None,
) -> Path | None:
    """Return the legacy project skill directory, if a root was supplied."""

    if project_root is None:
        return None
    return canonical_loader._legacy_project_skill_dirs(project_root)[0]


def _append_unique(target: list[str], path: str | Path) -> None:
    normalized = str(Path(path).expanduser().resolve())
    if normalized not in target:
        target.append(normalized)


def resolve_skills_paths(
    project_root: str | Path | None = None,
    user_skills_dir: str | Path | None = None,
) -> dict[str, list[str]]:
    """Project the discovery roots owned by the canonical loader.

    The returned mapping is informational only. Calling it never loads skills or
    creates another cache.
    """

    result: dict[str, list[str]] = {"user": [], "project": [], "managed": []}

    _append_unique(
        result["user"],
        canonical_loader.get_skills_path("userSettings"),
    )
    for root in canonical_loader._legacy_user_skill_dirs(user_skills_dir):
        _append_unique(result["user"], root)

    if project_root is not None:
        root = Path(project_root).expanduser().resolve()
        _append_unique(result["project"], root / ".claude" / "skills")
        for legacy_root in canonical_loader._legacy_project_skill_dirs(root):
            _append_unique(result["project"], legacy_root)

    _append_unique(
        result["managed"],
        canonical_loader.get_skills_path("policySettings"),
    )
    managed_override = get_clawcodex_managed_skills_dir()
    if managed_override is not None:
        _append_unique(result["managed"], managed_override)

    return result
