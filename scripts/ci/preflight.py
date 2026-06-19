"""Compute changed-file scopes for CI jobs.

The script is intentionally platform neutral. Workflows can source the emitted
``KEY=value`` file, while local developers can run it to see which gates would
run for a change.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_BRANCH = "dev-decoupling-refactor-b24b8cb"
DEFAULT_REMOTE = "origin"

PYTHON_SUFFIXES = {".py", ".pyi"}
DOC_SUFFIXES = {".md", ".mdx", ".rst"}
PACKAGE_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "MANIFEST.in",
}
CI_FILES = {
    ".pre-commit-config.yaml",
}
CI_PREFIXES = (
    ".gitcode/",
    ".github/",
    "scripts/ci/",
)
DOC_PREFIXES = (
    "docs/",
    "claude-code-wiki/",
)


def _run_git(args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        encoding="utf-8",
        errors="replace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def _tracked_files() -> list[str]:
    out = _run_git(["ls-files"])
    return sorted({line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()})


def _branch_name(ref: str) -> str | None:
    if ref.startswith("refs/heads/"):
        return ref.removeprefix("refs/heads/")
    if ref.startswith(f"{DEFAULT_REMOTE}/"):
        return ref.removeprefix(f"{DEFAULT_REMOTE}/")
    if ref.startswith(f"refs/remotes/{DEFAULT_REMOTE}/"):
        return ref.removeprefix(f"refs/remotes/{DEFAULT_REMOTE}/")
    if ref.startswith("refs/") or any(char in ref for char in "^~:"):
        return None
    return ref


def _base_candidates(base: str) -> list[str]:
    candidates = [base]
    branch = _branch_name(base)
    if branch:
        candidates.extend(
            [
                f"{DEFAULT_REMOTE}/{branch}",
                f"refs/remotes/{DEFAULT_REMOTE}/{branch}",
            ]
        )

    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def _fetch_base(base: str) -> None:
    branch = _branch_name(base)
    if not branch:
        return
    subprocess.run(
        [
            "git",
            "fetch",
            "--no-tags",
            DEFAULT_REMOTE,
            f"{branch}:refs/remotes/{DEFAULT_REMOTE}/{branch}",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _merge_base(base: str) -> str:
    for candidate in _base_candidates(base):
        merge_base = _run_git(["merge-base", candidate, "HEAD"], check=False)
        if merge_base:
            return merge_base

    _fetch_base(base)
    for candidate in _base_candidates(base):
        merge_base = _run_git(["merge-base", candidate, "HEAD"], check=False)
        if merge_base:
            return merge_base
    return ""


def _default_base() -> str:
    env_base = (
        os.environ.get("GITCODE_BASE_REF")
        or os.environ.get("BASE_REF")
        or os.environ.get("GITHUB_BASE_REF")
    )
    if env_base:
        return env_base

    remote_ref = f"{DEFAULT_REMOTE}/{DEFAULT_BASE_BRANCH}"
    exists = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", remote_ref],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if exists.returncode == 0:
        return remote_ref
    return "HEAD~1"


def _warn(message: str) -> None:
    """Print a warning to stderr, yellow when the stream supports color.

    Honors ``NO_COLOR`` (https://no-color.org/) and only emits ANSI color when
    stderr is a TTY, so redirected logs / CI captures stay plain text.
    """
    use_color = sys.stderr.isatty() and "NO_COLOR" not in os.environ
    if use_color:
        message = f"\033[33m{message}\033[0m"
    print(message, file=sys.stderr)


def _changed_files(base: str, all_files: bool) -> list[str]:
    if all_files:
        return _tracked_files()
    else:
        merge_base = _merge_base(base)
        if merge_base:
            out = _run_git(["diff", "--name-only", f"{merge_base}...HEAD"], check=False)
        else:
            out = ""
        if not out:
            # ``base`` could not be resolved to a merge base (typical causes:
            # the ref was never fetched locally, is misspelled, or fetch
            # failed). Falling back to ``HEAD~1..HEAD`` silently would only
            # check the *last* commit — which for a multi-commit PR hides the
            # earlier commits' changes and diverges from the PR gate. Warn
            # loudly so the operator notices the scope shrank, unless the
            # caller asked for ``HEAD~1`` explicitly (that is the expected
            # single-commit scope, not a degraded one).
            if base != "HEAD~1":
                _warn(
                    f"Warning: could not resolve base {base!r} to a merge base "
                    f"(fetch the ref or fix the spelling); falling back to "
                    f"HEAD~1..HEAD, so ONLY the last commit is checked. "
                    f"Run `git fetch` and verify the ref with "
                    f"`git rev-parse --verify {base}` before relying on this result."
                )
            out = _run_git(["diff", "--name-only", "HEAD~1..HEAD"], check=False)
        if not out:
            _warn("Warning: could not determine changed files; falling back to all tracked files.")
            return _tracked_files()
    return sorted({line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()})


def _is_doc(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in DOC_SUFFIXES or path.startswith(DOC_PREFIXES)


def _is_python(path: str) -> bool:
    return Path(path).suffix in PYTHON_SUFFIXES


def _is_orchestrator(path: str) -> bool:
    return path.startswith(("extensions/orchestrator/", "tests/orchestrator/"))


def _is_package(path: str) -> bool:
    return path in PACKAGE_FILES or path.startswith(("src/", "clawcodex_ext/", "extensions/"))


def _quote_list(paths: list[str]) -> str:
    return " ".join(shlex.quote(p) for p in paths)


def _python_files(files: list[str]) -> list[str]:
    return [p for p in files if _is_python(p)]


def _doc_files(files: list[str]) -> list[str]:
    return [p for p in files if _is_doc(p)]


def build_env(files: list[str]) -> dict[str, str]:
    python_files = _python_files(files)
    doc_files = _doc_files(files)
    package_files = [p for p in files if _is_package(p) or p in PACKAGE_FILES]
    orchestrator_files = [p for p in files if _is_orchestrator(p)]
    ci_files = [p for p in files if p in CI_FILES or p.startswith(CI_PREFIXES)]

    docs_only = bool(files) and len(doc_files) == len(files)
    run_python = bool(python_files or package_files or ci_files)
    run_orchestrator = bool(orchestrator_files or package_files or ci_files)
    run_package = bool(files) and not docs_only

    return {
        "CI_CHANGED_FILES": _quote_list(files),
        "CI_PYTHON_FILES": _quote_list(python_files),
        "CI_DOC_FILES": _quote_list(doc_files),
        "CI_DOCS_ONLY": str(docs_only).lower(),
        "CI_RUN_DOCS": str(bool(doc_files)).lower(),
        "CI_RUN_PYTHON": str(run_python).lower(),
        "CI_RUN_ORCHESTRATOR": str(run_orchestrator).lower(),
        "CI_RUN_PACKAGE": str(run_package).lower(),
    }


def write_env(env: dict[str, str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        for key, value in env.items():
            fh.write(f"{key}={shlex.quote(value)}\n")


def write_file_list(paths: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as fh:
        for path in paths:
            fh.write(f"{path}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=_default_base())
    parser.add_argument("--all", action="store_true", help="Use all tracked files")
    parser.add_argument("--output", default="ci_preflight.env")
    parser.add_argument("--python-files-output", default="ci_python_files.txt")
    parser.add_argument("--docs-files-output", default="ci_doc_files.txt")
    args = parser.parse_args()

    files = _changed_files(args.base, args.all)
    env = build_env(files)
    env["CI_PYTHON_FILE_LIST"] = args.python_files_output
    env["CI_DOC_FILE_LIST"] = args.docs_files_output
    write_env(env, ROOT / args.output)
    write_file_list(_python_files(files), ROOT / args.python_files_output)
    write_file_list(_doc_files(files), ROOT / args.docs_files_output)

    print("Changed files:")
    for path in files:
        print(f"  {path}")
    print("\nCI scope:")
    for key, value in env.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
