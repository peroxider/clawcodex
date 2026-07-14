"""Subprocess E2E for F-REC-L real REPL capture.

These tests spawn ``python3 -m extensions.recording.examples.repl_demo_driver``
and verify the produced ``.cast`` file is valid and contains the real
Rich ANSI output + captured input frames that only the full capture
pipeline can produce.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from extensions.recording.validate_cast import validate_cast

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_repl_demo_driver_produces_valid_cast(tmp_path: Path) -> None:
    """The demo driver writes a .cast that passes validation."""
    out = tmp_path / "real-repl.cast"
    cp = subprocess.run(
        [
            sys.executable,
            "-m",
            "extensions.recording.examples.repl_demo_driver",
            "--out",
            str(out),
            "--width",
            "120",
            "--height",
            "36",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPO_ROOT,
        input="explain layout\nrun tests\n",
    )
    assert cp.returncode == 0, f"stderr: {cp.stderr}"
    assert validate_cast(out) == []


def test_repl_demo_driver_contains_ansi_and_input_frames(tmp_path: Path) -> None:
    """The .cast contains real Rich ANSI output and at least one 'i' frame."""
    out = tmp_path / "real-repl.cast"
    cp = subprocess.run(
        [
            sys.executable,
            "-m",
            "extensions.recording.examples.repl_demo_driver",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPO_ROOT,
        input="explain layout\nrun tests\n",
    )
    assert cp.returncode == 0, f"stderr: {cp.stderr}"

    text = out.read_text(encoding="utf-8")
    raw_lines = text.splitlines()
    assert raw_lines
    header = json.loads(raw_lines[0])
    assert header["version"] == 2
    assert header["width"] == 120
    assert header["height"] == 36

    frames = [json.loads(line) for line in raw_lines[1:] if line.strip()]
    o_frames = [f for f in frames if f[1] == "o"]
    i_frames = [f for f in frames if f[1] == "i"]
    m_frames = [f for f in frames if f[1] == "m"]

    assert o_frames, "expected at least one output frame"
    assert any("\x1b[" in f[2] for f in o_frames), "expected real ANSI escape sequences"
    assert i_frames, "expected at least one input frame"
    assert any("run tests" in f[2] for f in i_frames), "expected captured user input"
    assert any("repl:prompt:start" in f[2] for f in m_frames), "expected prompt start marker"
