"""Build pytest target lists for CI smoke gates.

The workflows keep a small, stable smoke suite for fast feedback.  When a PR
changes pytest files, this helper appends those files to the relevant smoke
gate so newly added tests are not silently ignored.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path


CORE_PYTEST = (
    "tests/fast",
    "tests/config/test_config.py",
    "tests/config/test_config_system.py",
    "tests/config/test_effort.py",
    "tests/model",
    "tests/utils/test_combined_abort_signal.py",
    "tests/input/test_format.py",
    "tests/input/test_frontmatter_adapter.py",
    "tests/permissions/test_permission_modes.py",
    "tests/hooks/test_hook_config.py",
    "tests/skills/test_skills_frontmatter_yaml.py",
    "tests/bridge/test_jwt_utils.py",
    "tests/ci/test_gitcode_release.py",
)

ORCHESTRATOR_PYTEST = (
    "tests/orchestrator/test_local_tracker_parser.py",
    "tests/orchestrator/test_orchestrator_f39_intent.py",
    "tests/test_visualizer/test_orchestrator_link.py",
)

AGENT_SMOKE_PYTEST = (
    "tests/agent/test_agent_smoke_no_live_key.py",
    "tests/orchestrator/test_orchestrator_f49_transcript.py",
    "tests/orchestrator/test_orchestrator_f49_resume.py",
    "tests/orchestrator/test_orchestrator_workspace_hooks.py",
)

STABILITY_GATE_PYTEST = ("tests/stability_gate",)

RELEASE_SMOKE_PYTEST = (*CORE_PYTEST, *AGENT_SMOKE_PYTEST, *ORCHESTRATOR_PYTEST)

PRESETS: dict[str, tuple[str, ...]] = {
    "core": CORE_PYTEST,
    "orchestrator": ORCHESTRATOR_PYTEST,
    "agent-smoke": AGENT_SMOKE_PYTEST,
    "stability-gate": STABILITY_GATE_PYTEST,
    "release-smoke": RELEASE_SMOKE_PYTEST,
}


def normalize_path(path: str) -> str:
    return path.strip().lstrip("\ufeff").replace("\\", "/")


def is_pytest_file(path: str) -> bool:
    normalized = normalize_path(path)
    name = Path(normalized).name
    return (
        normalized.startswith("tests/")
        and normalized.endswith(".py")
        and (name.startswith("test_") or name.endswith("_test.py"))
    )


def read_changed_files(path: str | Path | None) -> list[str]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    return [
        normalize_path(line)
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def changed_pytest_files(
    paths: Iterable[str],
    *,
    include_prefixes: Sequence[str] | None = None,
    exclude_prefixes: Sequence[str] | None = None,
) -> list[str]:
    includes = tuple(normalize_path(prefix) for prefix in include_prefixes or ("tests/",))
    excludes = tuple(normalize_path(prefix) for prefix in exclude_prefixes or ())
    selected: list[str] = []
    seen: set[str] = set()

    for path in paths:
        normalized = normalize_path(path)
        if normalized in seen:
            continue
        if not is_pytest_file(normalized):
            continue
        if includes and not normalized.startswith(includes):
            continue
        if excludes and normalized.startswith(excludes):
            continue
        selected.append(normalized)
        seen.add(normalized)
    return selected


def build_pytest_targets(
    base_targets: Sequence[str],
    changed_files: Iterable[str] = (),
    *,
    include_prefixes: Sequence[str] | None = None,
    exclude_prefixes: Sequence[str] | None = None,
) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    covered_dirs = tuple(
        f"{normalize_path(target).rstrip('/')}/"
        for target in base_targets
        if not normalize_path(target).endswith(".py")
    )

    for target in base_targets:
        normalized = normalize_path(target)
        if normalized not in seen:
            targets.append(normalized)
            seen.add(normalized)

    for target in changed_pytest_files(
        changed_files,
        include_prefixes=include_prefixes,
        exclude_prefixes=exclude_prefixes,
    ):
        normalized = normalize_path(target)
        if normalized in seen or normalized.startswith(covered_dirs):
            continue
        targets.append(normalized)
        seen.add(normalized)
    return targets


def targets_for_preset(
    preset: str,
    changed_files: Iterable[str] = (),
    *,
    include_prefixes: Sequence[str] | None = None,
    exclude_prefixes: Sequence[str] | None = None,
) -> list[str]:
    return build_pytest_targets(
        PRESETS[preset],
        changed_files,
        include_prefixes=include_prefixes,
        exclude_prefixes=exclude_prefixes,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", choices=sorted(PRESETS))
    parser.add_argument("--changed-files-from")
    parser.add_argument("--include-prefix", action="append", default=None)
    parser.add_argument("--exclude-prefix", action="append", default=None)
    args = parser.parse_args(argv)

    changed_files = read_changed_files(args.changed_files_from)
    for target in targets_for_preset(
        args.preset,
        changed_files,
        include_prefixes=args.include_prefix,
        exclude_prefixes=args.exclude_prefix,
    ):
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
