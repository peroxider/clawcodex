"""Lightweight documentation checks for CI and pre-commit.

This intentionally stays smaller than OpenClaw's docs pipeline: ClawCodex does
not have an MDX docs site, i18n glossary, or generated docs catalog yet. The
goal is to keep pure-doc changes from bypassing every gate while avoiding a
site-scale toolchain.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOC_SUFFIXES = {".md", ".mdx", ".rst"}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "tmp",
}
SKIP_DOC_PARTS = {"raw"}

LINK_RE = re.compile(r"(!?\[[^\]\n]*\]\(([^)\n]+)\))")
EXTERNAL_SCHEMES = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "data:",
    "javascript:",
)


def _normalise(path: str) -> str:
    return path.replace("\\", "/").strip()


def _is_doc(path: Path) -> bool:
    return path.suffix.lower() in DOC_SUFFIXES


def _is_skipped_doc(path: Path) -> bool:
    try:
        rel_parts = path.relative_to(ROOT).parts
    except ValueError:
        return True
    return any(part in SKIP_DOC_PARTS or part.endswith(".raw") for part in rel_parts)


def _iter_all_docs() -> list[Path]:
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        proc = None

    if proc is not None:
        paths: list[Path] = []
        for raw in proc.stdout.splitlines():
            path = (ROOT / _normalise(raw)).resolve()
            if path.is_file() and _is_doc(path) and not _is_skipped_doc(path):
                paths.append(path)
        return sorted(paths)

    docs: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or not _is_doc(path):
            continue
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in rel_parts) or _is_skipped_doc(path):
            continue
        docs.append(path)
    return sorted(docs)


def _read_file_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _candidate_paths(raw_paths: list[str], *, all_docs: bool) -> list[Path]:
    if all_docs:
        return _iter_all_docs()

    paths: list[Path] = []
    for raw in raw_paths:
        rel = _normalise(raw)
        path = (ROOT / rel).resolve()
        if not path.exists() or not path.is_file() or not _is_doc(path) or _is_skipped_doc(path):
            continue
        try:
            path.relative_to(ROOT)
        except ValueError:
            continue
        paths.append(path)
    return sorted(set(paths))


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split()[0]
    return target.strip()


def _is_external_or_anchor(target: str) -> bool:
    lowered = target.lower()
    return (
        not target
        or target.startswith("#")
        or lowered.startswith(EXTERNAL_SCHEMES)
        or lowered.startswith("urn:")
    )


def _resolve_link(source: Path, target: str) -> Path | None:
    if _is_external_or_anchor(target):
        return None

    target_without_fragment = target.split("#", 1)[0].split("?", 1)[0]
    if not target_without_fragment:
        return None

    decoded = unquote(target_without_fragment)
    if decoded.startswith("/"):
        return (ROOT / decoded.lstrip("/")).resolve()
    return (source.parent / decoded).resolve()


def check_file(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    issues: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [f"{rel}:1: file is not valid UTF-8 ({exc})"]

    if text and not text.endswith("\n"):
        issues.append(f"{rel}: final newline missing")

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.rstrip(" \t") != line:
            issues.append(f"{rel}:{line_no}: trailing whitespace")
        if line.startswith(("<<<<<<< ", ">>>>>>> ")):
            issues.append(f"{rel}:{line_no}: merge conflict marker")

    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in LINK_RE.finditer(line):
            target = _link_target(match.group(2))
            resolved = _resolve_link(path, target)
            if resolved is None:
                continue
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                issues.append(f"{rel}:{line_no}: local link escapes repository: {target}")
                continue
            if not resolved.exists():
                issues.append(f"{rel}:{line_no}: local link target does not exist: {target}")

    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="Documentation files to check")
    parser.add_argument("--files-from", help="Read newline-delimited file paths")
    parser.add_argument("--all", action="store_true", help="Check all tracked documentation files")
    args = parser.parse_args(argv)

    raw_paths = list(args.paths)
    if args.files_from:
        raw_paths.extend(_read_file_list(ROOT / args.files_from))

    paths = _candidate_paths(raw_paths, all_docs=args.all)
    if not paths:
        print("No documentation files to check.")
        return 0

    issues: list[str] = []
    for path in paths:
        issues.extend(check_file(path))

    if issues:
        print("Documentation check failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print(f"Documentation check passed ({len(paths)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
