"""Tests for the recorder singleton + NullRecorder zero-cost path."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from clawcodex.telemetry import recorder as recorder_mod
from clawcodex.telemetry.config import TelemetryConfig
from clawcodex.telemetry.recorder import (
    _NullRecorder,
    _TelemetryRecorderImpl,
    get_recorder,
    override_recorder,
    reset_recorder_for_tests,
)
from clawcodex.telemetry.redaction import RedactionConfig, Redactor
from clawcodex.telemetry.storage import utc_date, utc_now


@pytest.fixture(autouse=True)
def _reset_recorder():
    reset_recorder_for_tests()
    yield
    reset_recorder_for_tests()


def test_default_is_null_recorder():
    r = get_recorder()
    assert isinstance(r, _NullRecorder)
    assert r.enabled is False
    # All methods are no-ops and must not raise.
    r.record_session_start(session_id="x", entrypoint="cli")
    r.record_session_end(session_id="x", duration_s=0.0, exit_status=0)
    r.record_command_run(session_id="x", command_name="repl")
    try:
        raise RuntimeError("test")
    except RuntimeError as exc:
        r.record_error(session_id="x", exc=exc)
    r.record_tool_summary(session_id="x", tool_name="bash")
    r.flush()
    r.close()


def test_override_recorder_runs_user_instance(tmp_path):
    storage = recorder_mod.LocalJsonlStorage(tmp_path / "telemetry", 7)
    impl = _TelemetryRecorderImpl(
        cfg=TelemetryConfig(enabled=True, storage_dir=tmp_path / "telemetry"),
        storage=storage,
        aggregator=recorder_mod.DailyAggregator(storage),
        redactor=Redactor(RedactionConfig(), (str(tmp_path),)),
        reporters=recorder_mod.CompositeReporter(),
    )
    override_recorder(impl)
    r = get_recorder()
    assert r is impl
    r.record_session_start(session_id="s1", entrypoint="cli", platform="Linux")
    today = utc_date(utc_now())
    rows = storage.read_day("events", today)
    assert any(row["type"] == "session_start" for row in rows)
    override_recorder(None)
    assert isinstance(get_recorder(), _NullRecorder)


def test_recorder_writes_crash_event(tmp_path):
    storage = recorder_mod.LocalJsonlStorage(tmp_path / "telemetry", 7)
    impl = _TelemetryRecorderImpl(
        cfg=TelemetryConfig(enabled=True, storage_dir=tmp_path / "telemetry"),
        storage=storage,
        aggregator=recorder_mod.DailyAggregator(storage),
        redactor=Redactor(RedactionConfig(), (str(tmp_path),)),
        reporters=recorder_mod.CompositeReporter(),
    )
    try:
        raise ValueError("boom")
    except ValueError as exc:
        impl.record_error(session_id="s1", exc=exc)
    today = utc_date(utc_now())
    crashes = storage.read_day("crashes", today)
    assert crashes and crashes[0]["fields"]["error_class"] == "ValueError"
    assert len(crashes[0]["fields"]["fingerprint"]) == 16
