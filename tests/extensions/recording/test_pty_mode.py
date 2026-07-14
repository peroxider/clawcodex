"""End-to-end tests for F-REC-M: ``clawcodex record --mode pty``.

F-REC-M adds a second recording mode to :mod:`extensions.recording.cli`
that forks a real pseudo-terminal and captures the **full screen** —
including the ``❯`` prompt bar, line-edit, cursor moves, and any Rich
output — which F-REC-L's Rich tee cannot capture because prompt_toolkit
renders directly to the TTY, not via Rich.

The native backend uses only the Python standard-library ``pty``
module, so it works even when the external ``asciinema`` CLI is not
installed. An optional ``asciinema`` backend is retained for users who
prefer the Rust CLI.

These tests cover the reachable surfaces of the new mode:

* the ``--help`` text documents the mode and both backends
* ``--mode pty`` is mutually exclusive with ``--sources`` and ``--auto``
* the native backend records a short shell command into a valid
  asciicast v2 file
* the asciinema backend prints a clear install hint when asciinema is
  absent (skip-able when asciinema is present)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _cli_argv(*extra: str) -> list[str]:
    """Build a ``python -m clawcodex_ext.cli.main record ...`` argv."""
    return [
        sys.executable,
        "-m",
        "clawcodex_ext.cli.main",
        "record",
        *extra,
    ]


def test_pty_mode_help_mentions_pty_mode() -> None:
    """``--help`` advertises ``--mode pty`` and the backends."""
    result = subprocess.run(
        _cli_argv("--help"),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0
    assert "--mode {structured,pty}" in result.stdout, (
        f"--help output missing --mode choices; got {result.stdout!r}"
    )
    assert "--pty-cmd" in result.stdout, (
        f"--help output missing --pty-cmd flag; got {result.stdout!r}"
    )
    assert "--pty-backend" in result.stdout, (
        f"--help output missing --pty-backend flag; got {result.stdout!r}"
    )


def test_pty_mode_native_records_short_bash_demo_into_valid_cast(
    tmp_path: Path,
) -> None:
    """Native backend produces a valid .cast from a short shell command."""
    cast_path = tmp_path / "pty-native.cast"
    result = subprocess.run(
        _cli_argv(
            "--mode", "pty",
            "--pty-backend", "native",
            "--pty-cmd", "bash -c 'echo hello-from-pty; sleep 0.2'",
            "--no-pty-auto-exit",
            "--out", str(cast_path),
        ),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"native pty-mode smoke failed; rc={result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert cast_path.exists(), (
        f"native backend did not produce {cast_path}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )

    from extensions.recording.validate_cast import validate_cast

    errors = validate_cast(cast_path)
    assert errors == [], f"validator rejected the native pty-mode .cast: {errors!r}"

    raw = cast_path.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    assert header["version"] == 2, (
        f"native pty-mode .cast header is not asciicast v2: {header!r}"
    )
    full_body = "\n".join(raw[1:])
    assert "hello-from-pty" in full_body, (
        f"inner command's stdout was not captured; "
        f"first 200 chars of body = {full_body[:200]!r}"
    )


def test_pty_backend_asciinema_missing_returns_clear_error(
    tmp_path: Path,
) -> None:
    """When ``asciinema`` is absent from PATH the CLI prints an install hint.

    Uses an isolated empty PATH directory so asciinema (if it happens to
    be installed system-wide for the developer) cannot leak in.
    """
    empty_path_dir = tmp_path / "no-asciinema-bin"
    empty_path_dir.mkdir()
    env = {
        "PATH": str(empty_path_dir),
        "PYTHONPATH": str(_REPO_ROOT),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(
        _cli_argv(
            "--mode", "pty",
            "--pty-backend", "asciinema",
            "--out", str(tmp_path / "demo.cast"),
        ),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert result.returncode == 2, (
        f"asciinema backend without asciinema should exit 2; "
        f"got rc={result.returncode}; stderr={result.stderr!r}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "asciinema" in combined, (
        f"expected 'asciinema' in output; got stdout={result.stdout!r}; "
        f"stderr={result.stderr!r}"
    )
    assert "apt install asciinema" in combined, (
        f"expected apt install hint; got stdout={result.stdout!r}; "
        f"stderr={result.stderr!r}"
    )


def test_pty_mode_mutually_excludes_sources(tmp_path: Path) -> None:
    """``--mode pty --sources X`` errors out at parse time."""
    result = subprocess.run(
        _cli_argv(
            "--mode", "pty",
            "--sources", "orchestrator",
            "--out", str(tmp_path / "x.cast"),
        ),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode != 0, (
        f"--mode pty --sources should be rejected; got rc=0; "
        f"stderr={result.stderr!r}"
    )
    assert "mutually exclusive" in (result.stdout + result.stderr).lower(), (
        f"expected 'mutually exclusive' error; got stdout={result.stdout!r}; "
        f"stderr={result.stderr!r}"
    )


def test_pty_mode_mutually_excludes_auto(tmp_path: Path) -> None:
    """``--mode pty --auto`` errors out at parse time."""
    result = subprocess.run(
        _cli_argv(
            "--mode", "pty",
            "--auto",
            "--out", str(tmp_path / "x.cast"),
        ),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode != 0, (
        f"--mode pty --auto should be rejected; got rc=0; "
        f"stderr={result.stderr!r}"
    )
    assert "mutually exclusive" in (result.stdout + result.stderr).lower(), (
        f"expected 'mutually exclusive' error; got stdout={result.stdout!r}; "
        f"stderr={result.stderr!r}"
    )


@pytest.mark.skipif(
    shutil.which("asciinema") is None,
    reason="asciinema CLI not installed on this runner",
)
def test_pty_backend_asciinema_records_short_command(tmp_path: Path) -> None:
    """When asciinema is on PATH, the asciinema backend works."""
    cast_path = tmp_path / "pty-asciinema.cast"
    result = subprocess.run(
        _cli_argv(
            "--mode", "pty",
            "--pty-backend", "asciinema",
            "--pty-cmd", "bash -c 'echo hello-asciinema; sleep 1'",
            "--no-pty-auto-exit",
            "--pty-overwrite",
            "--title", "F-REC-M asciinema smoke",
            "--out", str(cast_path),
        ),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"asciinema backend smoke failed; rc={result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert cast_path.exists(), (
        f"asciinema backend did not produce {cast_path}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )

    from extensions.recording.validate_cast import validate_cast

    errors = validate_cast(cast_path)
    assert errors == [], f"validator rejected the asciinema .cast: {errors!r}"