#!/usr/bin/env python3
"""Bump static version references to today's CalVer date.

Usage
-----
    python scripts/ci/bump_version.py           # dry-run (default)
    python scripts/ci/bump_version.py --apply    # write changes

What it updates
---------------
Files that CANNOT dynamically read ``clawcodex_ext._version.__version__``
because they are shell scripts, lock files, or test fixtures:

  * install.sh        — INSTALLER_VERSION / CLAWCODEX_VERSION
  * uv.lock           — clawcodex-dev-mind package version
  * tests/            — test assertions that hard-code the version string

These files are updated so that a tagged release has consistent version
numbers everywhere, even though the runtime version is always dynamic.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def calver() -> str:
    today = date.today()
    return f"{today.year}.{today.month}.{today.day}"


# ── file-level patchers ──────────────────────────────────────────────
PATCHERS: list[dict] = [
    # install.sh — two readonly vars on consecutive lines
    {
        "path": "install.sh",
        "pattern": re.compile(
            r'(readonly INSTALLER_VERSION=")\d+\.\d+\.\d+(")'
        ),
        "replacement": r'\g<1>{ver}\g<2>',
    },
    {
        "path": "install.sh",
        "pattern": re.compile(
            r'(readonly CLAWCODEX_VERSION=")\d+\.\d+\.\d+(")'
        ),
        "replacement": r'\g<1>{ver}\g<2>',
    },
    # uv.lock — clawcodex-dev-mind entry (must match exactly one)
    {
        "path": "uv.lock",
        "pattern": re.compile(
            r'(name = "clawcodex-dev-mind"\n)version = "\d+\.\d+\.\d+"'
        ),
        "replacement": r'\g<1>version = "{ver}"',
    },
    # test fixtures
    {
        "path": "tests/services/pipe_ipc/test_pipe_ipc_models.py",
        "pattern": re.compile(r'(version=)"\d+\.\d+\.\d+"'),
        "replacement": r'\g<1>"{ver}"',
    },
    {
        "path": "tests/telemetry/telemetry_issue_push_real.py",
        "pattern": re.compile(r'("app_version": ")\d+\.\d+\.\d+'),
        "replacement": r'\g<1>{ver}',
    },
    {
        "path": "tests/telemetry/test_storage.py",
        "pattern": re.compile(r'("version": ")\d+\.\d+\.\d+"'),
        "replacement": r'\g<1>{ver}"',
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump static version refs")
    parser.add_argument("--apply", action="store_true", help="write changes")
    opts = parser.parse_args()

    ver = calver()
    n_changed = 0

    for patcher in PATCHERS:
        path = REPO_ROOT / patcher["path"]
        if not path.exists():
            print(f"  SKIP  {patcher['path']}  (not found)")
            continue

        old_text = path.read_text(encoding="utf-8")
        new_text = patcher["pattern"].sub(
            patcher["replacement"].replace("{ver}", ver),
            old_text,
        )

        if old_text == new_text:
            print(f"  …     {patcher['path']}  (already up to date)")
            continue

        n_changed += 1
        if opts.apply:
            path.write_text(new_text, encoding="utf-8")
            print(f"  ✏️  {patcher['path']}  →  {ver}")
        else:
            print(f"  DRY   {patcher['path']}  →  {ver}")

    if n_changed and not opts.apply:
        print(f"\nWould update {n_changed} file(s). Re-run with --apply to write.")
    elif n_changed:
        print(f"\n{n_changed} file(s) updated to {ver}.")
    else:
        print(f"\nAll files already at {ver} — nothing to do.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
