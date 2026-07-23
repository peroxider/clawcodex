"""Discover POS agent bundles in a workspace for SOP auto-activation."""

from __future__ import annotations

import logging
from pathlib import Path

from .bundle_skills import _bundle_skill_search_dirs

logger = logging.getLogger(__name__)

_BUNDLE_NAME_PREFIXES = ("JiuwenAgent",)


def _is_sop_skill_name(name: str) -> bool:
    return isinstance(name, str) and name.endswith("-skill")


def _looks_like_pos_bundle(path: Path, workspace: Path) -> bool:
    if not path.is_dir():
        return False
    from ..adapters import DEFAULTS

    if DEFAULTS.tool_authoring.iter_bundle_tool_dirs(path):
        return True
    for skill_dir in _bundle_skill_search_dirs(path, workspace):
        if any(skill_dir.glob("*-skill.md")):
            return True
    return False


def list_workspace_bundle_candidates(workspace: Path) -> list[Path]:
    """Return candidate bundle roots under *workspace* (deduplicated by name)."""
    ws = workspace.resolve()
    by_name: dict[str, Path] = {}

    clawcodex_root = ws / ".clawcodex"
    if clawcodex_root.is_dir():
        for child in sorted(clawcodex_root.iterdir()):
            if not child.is_dir():
                continue
            if not child.name.startswith(_BUNDLE_NAME_PREFIXES):
                continue
            if _looks_like_pos_bundle(child, ws):
                by_name.setdefault(child.name, child)

    skills_root = ws / "skills"
    if skills_root.is_dir():
        for child in sorted(skills_root.iterdir()):
            if not child.is_dir():
                continue
            if not child.name.startswith(_BUNDLE_NAME_PREFIXES):
                continue
            preferred = by_name.get(child.name) or child
            if _looks_like_pos_bundle(preferred, ws) or any(child.glob("*-skill.md")):
                by_name[child.name] = preferred

    return sorted(by_name.values(), key=lambda p: p.name)


def _skill_hits_in_bundle(
    bundle_path: Path,
    workspace: Path,
    skill_names: list[str],
) -> int:
    search_dirs = _bundle_skill_search_dirs(bundle_path, workspace)
    hits = 0
    for skill in skill_names:
        if not _is_sop_skill_name(skill):
            continue
        md_name = skill if skill.endswith(".md") else f"{skill}.md"
        if any((d / md_name).is_file() for d in search_dirs):
            hits += 1
    return hits


def discover_workspace_bundle(
    workspace: Path,
    *,
    agent_skills: list[str] | None = None,
) -> Path | None:
    """Pick the best POS bundle for an overview agent in *workspace*."""
    candidates = list_workspace_bundle_candidates(workspace)
    if not candidates:
        return None

    skills = [s for s in (agent_skills or []) if _is_sop_skill_name(s)]
    if not skills:
        return candidates[0] if len(candidates) == 1 else None

    best_path: Path | None = None
    best_hits = 0
    for bundle_path in candidates:
        hits = _skill_hits_in_bundle(bundle_path, workspace, skills)
        if hits > best_hits:
            best_hits = hits
            best_path = bundle_path

    if best_path is not None and best_hits > 0:
        return best_path
    return candidates[0] if len(candidates) == 1 else None


def overview_has_sop_skills(agent: dict) -> bool:
    skills = agent.get("skills") or []
    return any(_is_sop_skill_name(s) for s in skills if isinstance(s, str))
