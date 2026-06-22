"""Initialize a local development checkout.

This helper is intentionally local-only: it installs the Git pre-commit hook when
``pre-commit`` is available and creates the ignored ``.env`` release template
from ``.env.example`` when missing. It never overwrites existing secrets.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from env_loader import ROOT, ensure_dotenv


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _install_pre_commit_hook() -> bool:
    config = ROOT / ".pre-commit-config.yaml"
    if not config.exists():
        print("[SKIP] .pre-commit-config.yaml is missing")
        return False

    available = subprocess.run(
        [sys.executable, "-m", "pre_commit", "--version"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if available.returncode != 0:
        print("[SKIP] pre-commit is not installed in this Python environment")
        print('       install dev dependencies first, for example: pip install -e ".[dev]"')
        return False

    result = subprocess.run(
        [sys.executable, "-m", "pre_commit", "install", "--hook-type", "pre-commit"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print("[FAIL] pre-commit hook install failed")
        if result.stdout.strip():
            print(result.stdout.rstrip())
        return False

    print("[PASS] installed .git/hooks/pre-commit")
    return True


def _bootstrap_env() -> bool:
    env_path, created = ensure_dotenv()
    if created:
        try:
            env_path.chmod(0o600)
        except OSError:
            pass
        print(f"[PASS] created {_relative(env_path)} from .env.example")
        print("       fill tokens locally before running release publish commands")
        return True

    print(f"[PASS] {_relative(env_path)} already exists; left unchanged")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize this checkout for local development.")
    parser.add_argument(
        "--skip-pre-commit",
        action="store_true",
        help="Do not install the local Git pre-commit hook.",
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="Do not create .env from .env.example when missing.",
    )
    args = parser.parse_args(argv)

    print("ClawCodex developer setup")
    if args.skip_pre_commit:
        print("[SKIP] pre-commit hook install disabled by flag")
    else:
        _install_pre_commit_hook()

    if args.skip_env:
        print("[SKIP] .env bootstrap disabled by flag")
    else:
        _bootstrap_env()

    print("[DONE] local development setup finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
