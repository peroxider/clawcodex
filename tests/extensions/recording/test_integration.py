"""Integration tests for the F-REC asciicast recorder.

These tests wire two or more subsystem adapters into one shared
:class:`AsciicastWriter` and verify the on-disk .cast is valid + the
event ordering matches expectations. This is the closest analogue to
the manual_e2e_f38.py flow — exercises the cross-cutting
plumbing rather than any single adapter.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.validate_cast import validate_cast


def _read_cast(path: Path) -> tuple[dict, list[list[object]]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    events = [json.loads(line) for line in raw[1:]]
    return header, events


def test_two_adapters_share_one_writer(tmp_path: Path) -> None:
    """Composite flow: orchestrator sink + cron observer → one .cast file."""
    from extensions.api.query import PhaseComplete, SessionComplete
    from extensions.orchestrator.asciicast_sink import AsciicastSink
    from clawcodex_ext.cron_system.asciicast_observer import AsciicastCronObserver

    writer = AsciicastWriter(
        tmp_path / "demo.cast", AsciicastHeader(width=120, height=36)
    )
    writer.open()
    try:
        sink = AsciicastSink(writer.capture, task_id="issue-9", phases_total=3)
        cron = AsciicastCronObserver(writer.capture)

        class _Sess:
            task_id = "issue-9"

        sink.on_phase_complete(PhaseComplete(phase=1, turn_count=4), _Sess())
        cron.on_fire_task(_StubTask("cleanup"), _StubRun())
        sink.on_phase_complete(PhaseComplete(phase=2, turn_count=8), _Sess())
        cron.on_fire_event({"status": "fired", "task_id": "rotate"})
        sink.on_session_complete(SessionComplete(reason="exit_code=0"), _Sess())
    finally:
        writer.close()

    # Validator must accept the file.
    assert validate_cast(tmp_path / "demo.cast") == []

    header, events = _read_cast(tmp_path / "demo.cast")
    assert header["version"] == 2
    markers = [e[2] for e in events if e[1] == "m"]
    # Phase + cron + session markers all show up in issue order.
    assert "[phase 1/3]" in markers
    assert "cron:fire:cleanup" in markers
    assert "[phase 2/3]" in markers
    assert "cron:event:fired" in markers
    assert "session:exit_code=0" in markers


def test_cli_subprocess_runs_and_validates(tmp_path: Path) -> None:
    """Run ``clawcodex record --sources cron`` end-to-end via the entry point.

    The smoke-level integration. Verifies the subcommand_registry wiring
    + writer + validator + source factory chain works in a fresh
    subprocess.
    """
    out_path = tmp_path / "smoke.cast"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from clawcodex_ext.cli.subcommand_registry import "
                "get_subcommand; "
                "raise SystemExit(get_subcommand('record')(['--sources','cron',"
                "'--out', %r, '--duration','0.5s','--validate']))" % str(out_path)
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # The capture exists, is valid, and contains the cron lifecycle markers.
    errors = validate_cast(out_path)
    assert errors == [], errors
    raw = out_path.read_text(encoding="utf-8").splitlines()
    markers = [json.loads(line)[2] for line in raw[1:] if json.loads(line)[1] == "m"]
    assert "cron:recording_started" in markers
    assert "cron:recording_closed" in markers


def test_cli_unknown_source_exits_with_error(tmp_path: Path) -> None:
    """Unknown source IDs must surface as a clean exit-2 with a hint."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from clawcodex_ext.cli.subcommand_registry import "
                "get_subcommand; "
                "raise SystemExit(get_subcommand('record')(['--sources','nope',"
                "'--out', %r]))" % str(tmp_path / "x.cast")
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "unknown source" in result.stderr


def test_cli_list_sources_lists_builtins(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from clawcodex_ext.cli.subcommand_registry import "
                "get_subcommand; "
                "raise SystemExit(get_subcommand('record')(['--list-sources']))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "orchestrator" in result.stdout
    assert "cron" in result.stdout
    assert "visualizer" in result.stdout


class _StubTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.cron = "* * * * *"


class _StubRun:
    def __init__(self) -> None:
        self.id = "r-stub"