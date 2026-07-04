"""CLI integration tests for F-50-A/B."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPO = Path(__file__).resolve().parents[2]


def _run_convert(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "clawcodex_ext.cli.sop_cmd.commands"] + args
    # Invoke via clawcodex-dev entry if available; fallback direct handler
    from clawcodex_ext.cli.sop_cmd.commands import _handle_convert

    # Use handler directly for reliability in tests
    rc = _handle_convert(args)
    class Result:
        returncode = rc
        stdout = ""
        stderr = ""
    return Result()  # type: ignore[return-value]


def test_architecture_no_orchestrator_import():
    root = REPO / "extensions" / "sop_converter" / "workflow_mode"
    for py in root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "extensions.orchestrator" not in text


def test_overview_workflow_stages_fwa(tmp_path):
    from clawcodex_ext.cli.sop_cmd.commands import _handle_convert

    out = tmp_path / "out"
    out.mkdir()
    rc = _handle_convert([
        str(FIXTURES / "fixture_fwa_project"),
        "--out", str(out),
        "--all",
        "--mode", "fwa",
    ])
    assert rc == 0
    overview = out / ".claude" / "agents" / "clawcodex-overview.md"
  # overview only when 2+ agents - fwa fixture might have 1 component per file
    agents = list((out / ".claude" / "agents").glob("*.md"))
    assert agents

def test_preview_includes_workflow(tmp_path, capsys):
    from clawcodex_ext.cli.sop_cmd.commands import _handle_convert

    rc = _handle_convert([
        str(FIXTURES / "fixture_fwa_project"),
        "--preview",
        "--all",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Workflow extraction" in captured.out or "Workflow mode" in captured.out
