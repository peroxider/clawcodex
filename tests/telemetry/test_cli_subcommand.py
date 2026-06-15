"""Tests for the telemetry CLI subcommands."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

from clawcodex.telemetry import cli
from clawcodex.telemetry.config import TelemetryConfig, load_config
from clawcodex.telemetry.recorder import reset_recorder_for_tests


def test_status_default(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAW_TELEMETRY_ENABLED", raising=False)
    reset_recorder_for_tests()
    rc = cli.run_status([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Telemetry status" in out
    assert "enabled        : False" in out


def test_enable_prints_snippet(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = cli.run_enable([])
    out = capsys.readouterr().out
    assert rc == 0
    # The snippet should be parseable JSON.
    assert "telemetry" in out
    # Find the JSON blob in the output.
    start = out.find("{")
    assert start != -1
    blob = out[start:]
    parsed = json.loads(blob)
    assert "telemetry" in parsed
    assert "storage_dir" in parsed["telemetry"]


def test_disable_prints_snippet(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = cli.run_disable([])
    out = capsys.readouterr().out
    assert rc == 0
    start = out.find("{")
    parsed = json.loads(out[start:])
    assert parsed["telemetry"]["enabled"] is False


def test_preview_when_disabled(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAW_TELEMETRY_ENABLED", raising=False)
    reset_recorder_for_tests()
    rc = cli.run_preview([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "disabled" in out


def test_main_dispatches_to_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Telemetry status" in out


def test_main_unknown_subcommand(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = cli.main(["bogus"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "unknown subcommand" in captured.out
