"""Resolve third-party dependencies declared by an SDK source tree."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore[import-not-found]


@dataclass(frozen=True)
class SdkDependencySpec:
    """SDK dependency declarations discovered during ``sop convert``."""

    requirements: tuple[str, ...]
    source: str
    raw_path: str


def resolve_sdk_dependencies(sdk_source_dir: str | Path) -> SdkDependencySpec:
    """Resolve runtime dependencies from ``pyproject.toml`` or ``requirements.txt``.

    Priority is:
    1. ``[project].dependencies`` in ``pyproject.toml``
    2. ``requirements.txt``
    3. empty dependency set
    """

    root = Path(sdk_source_dir).expanduser().resolve()

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        deps = _parse_pyproject_dependencies(pyproject)
        if deps:
            return SdkDependencySpec(
                requirements=tuple(deps),
                source="pyproject.toml",
                raw_path=str(pyproject),
            )

    requirements = root / "requirements.txt"
    if requirements.is_file():
        deps = _parse_requirements_txt(requirements)
        if deps:
            return SdkDependencySpec(
                requirements=tuple(deps),
                source="requirements.txt",
                raw_path=str(requirements),
            )

    return SdkDependencySpec(requirements=(), source="empty", raw_path=str(root))


def _parse_pyproject_dependencies(path: Path) -> list[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    project = data.get("project")
    if not isinstance(project, dict):
        return []

    deps = project.get("dependencies")
    if not isinstance(deps, list):
        return []

    sdk_names = {_normalise_name(path.parent.name)}
    project_name = project.get("name")
    if isinstance(project_name, str) and project_name.strip():
        sdk_names.add(_normalise_name(project_name))

    result: list[str] = []
    seen: set[str] = set()
    for dep in deps:
        if not isinstance(dep, str):
            continue
        dep = dep.strip()
        if not dep:
            continue
        dep_name = _requirement_name(dep)
        if dep_name and _normalise_name(dep_name) in sdk_names:
            continue
        if dep not in seen:
            result.append(dep)
            seen.add(dep)
    return result


def _parse_requirements_txt(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = _strip_inline_comment(line).strip()
        if not line:
            continue
        if _is_requirements_directive(line):
            continue
        if line not in seen:
            result.append(line)
            seen.add(line)
    return result


def _strip_inline_comment(line: str) -> str:
    """Strip comments that are separated from the requirement by whitespace."""

    return re.split(r"\s+#", line, maxsplit=1)[0]


def _is_requirements_directive(line: str) -> bool:
    return line.startswith((
        "-",
        "--",
    ))


def _requirement_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    if not match:
        return ""
    return match.group(1)


def _normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()
