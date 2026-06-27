"""Lightweight supply-chain checks for Agent repository changes."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE = "origin"

SCAN_SUFFIXES = {
    ".py",
    ".pyi",
    ".pth",
    ".sh",
    ".bash",
    ".ps1",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".json",
}
SKIP_PREFIXES = {
    ".git/",
    ".venv/",
    "src/upstream/",
    "claude-code-wiki/",
    "patches/",
    "demos/",
}
SKIP_FILES = {
    # The scanner contains the literal pattern strings it searches for, so
    # scanning itself creates noisy self-referential findings.
    "scripts/ci/supply_chain_audit.py",
}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    (
        "secret-assignment",
        re.compile(
            r"(?i:(?:api[_-]?key|secret|token|password))\s*[:=]\s*['\"]"
            r"(?=[^'\"]{24,}['\"])(?=[^'\"]*[0-9])(?=[^'\"]*[a-z])(?=[^'\"]*[A-Z])"
            r"[A-Za-z0-9_./+=:-]{24,}['\"]"
        ),
    ),
    (
        "base64-exec",
        re.compile(
            r"(?is)(base64\.b64decode|frombase64string|base64\s+-d).{0,160}(exec|eval|invoke-expression|iex)"
        ),
    ),
    (
        "obfuscated-subprocess",
        re.compile(
            r"(?is)(subprocess\.(?:run|Popen|call)|os\.system|popen)\s*\("
            r".{0,200}(base64|marshal|zlib|exec\(|eval\()"
        ),
    ),
]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str


@dataclass(frozen=True)
class ChangedScope:
    files: list[str]
    diff_range: str | None
    fail_safe: bool = False


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        encoding="utf-8",
        errors="replace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_git(args: list[str], *, check: bool = True) -> str:
    proc = _git(args)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode,
            ["git", *args],
            output=proc.stdout,
            stderr=proc.stderr,
        )
    return proc.stdout.strip()


def _tracked_files() -> list[str]:
    return sorted(
        {line.strip().replace("\\", "/") for line in _run_git(["ls-files"]).splitlines() if line}
    )


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


def _changed_scope(base: str) -> ChangedScope:
    merge_base = _merge_base(base)
    diff_range = f"{merge_base}...HEAD" if merge_base else None

    if diff_range:
        out = _run_git(["diff", "--name-only", "--diff-filter=ACMR", diff_range], check=False)
    else:
        out = ""

    if not out:
        diff_range = "HEAD~1..HEAD"
        out = _run_git(["diff", "--name-only", "--diff-filter=ACMR", diff_range], check=False)

    if not out:
        print(
            "Warning: could not determine changed files; scanning all tracked files.",
            file=sys.stderr,
        )
        return ChangedScope(_tracked_files(), None, fail_safe=True)

    files = sorted({line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()})
    return ChangedScope(files, diff_range)


HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _added_lines(diff_range: str) -> dict[str, list[tuple[int, str]]]:
    proc = _git(["diff", "--unified=0", "--diff-filter=ACMR", diff_range])
    if proc.returncode != 0:
        return {}

    added: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current_path: str | None = None
    new_line: int | None = None

    for line in proc.stdout.splitlines():
        if line.startswith("diff --git "):
            current_path = None
            new_line = None
            continue
        if line.startswith("+++ b/"):
            current_path = line[6:].replace("\\", "/")
            new_line = None
            continue
        if line.startswith("@@ "):
            match = HUNK_RE.search(line)
            new_line = int(match.group(1)) if match else None
            continue
        if current_path is None or new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added[current_path].append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_line += 1

    return dict(added)


def _should_scan(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in SKIP_FILES:
        return False
    if any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    return Path(normalized).suffix.lower() in SCAN_SUFFIXES or Path(normalized).name in {
        "requirements.txt",
        "MANIFEST.in",
    }


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _added_line_number(text: str, entries: list[tuple[int, str]], offset: int) -> int:
    index = text.count("\n", 0, offset)
    if 0 <= index < len(entries):
        return entries[index][0]
    return entries[0][0] if entries else 1


def scan_file(path: str) -> list[Finding]:
    full = ROOT / path
    if not full.is_file():
        return []
    try:
        text = full.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[Finding] = []
    if full.suffix == ".pth":
        findings.append(
            Finding(path, 1, "pth-file", ".pth files can execute import lines at install time")
        )

    name = full.name.lower()
    if name in {"setup.py", "setup.cfg", "pyproject.toml"}:
        for hook in ("cmdclass", "setup_requires", "dependency_links"):
            if hook in text:
                findings.append(Finding(path, 1, "install-hook", f"contains {hook}"))

    for rule, pattern in PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).splitlines()[0].strip()
            findings.append(Finding(path, _line_number(text, match.start()), rule, raw[:180]))
    return findings


def scan_added_lines(path: str, entries: list[tuple[int, str]]) -> list[Finding]:
    if not entries:
        return []

    findings: list[Finding] = []
    suffix = Path(path).suffix.lower()
    if suffix == ".pth":
        findings.append(
            Finding(
                path,
                entries[0][0],
                "pth-file",
                ".pth files can execute import lines at install time",
            )
        )

    text = "\n".join(line for _, line in entries)
    name = Path(path).name.lower()
    if name in {"setup.py", "setup.cfg", "pyproject.toml"}:
        for hook in ("cmdclass", "setup_requires", "dependency_links"):
            offset = text.find(hook)
            if offset >= 0:
                findings.append(
                    Finding(
                        path,
                        _added_line_number(text, entries, offset),
                        "install-hook",
                        f"contains {hook}",
                    )
                )

    for rule, pattern in PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).splitlines()[0].strip()
            findings.append(
                Finding(path, _added_line_number(text, entries, match.start()), rule, raw[:180])
            )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/dev-decoupling-refactor-0573f4c")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    scope = (
        ChangedScope(_tracked_files(), None, fail_safe=True)
        if args.all
        else _changed_scope(args.base)
    )
    added_lines = _added_lines(scope.diff_range) if scope.diff_range else {}
    candidates = scope.files
    files = [path for path in candidates if _should_scan(path)]
    if scope.diff_range and not scope.fail_safe:
        findings = [
            finding
            for path in files
            for finding in scan_added_lines(path, added_lines.get(path, []))
        ]
    else:
        findings = [finding for path in files for finding in scan_file(path)]

    if findings:
        print("Supply-chain audit findings:")
        for item in findings:
            print(f"{item.path}:{item.line}: {item.rule}: {item.text}")
        return 1

    print(f"Supply-chain audit passed ({len(files)} scanned files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
