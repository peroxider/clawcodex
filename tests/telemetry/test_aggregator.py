"""Tests for DailyAggregator."""
from __future__ import annotations

import time
from pathlib import Path

from clawcodex.telemetry.aggregator import DailyAggregator
from clawcodex.telemetry.storage import LocalJsonlStorage, utc_date, utc_now


def _storage(tmp_path: Path) -> LocalJsonlStorage:
    return LocalJsonlStorage(tmp_path / "telemetry", retention_days=7)


def _session_start(sid, fields=None):
    return {
        "type": "session_start",
        "timestamp": time.time(),
        "session_id": sid,
        "schema_version": 1,
        "fields": {
            "entrypoint": "cli",
            "client_type": "cli",
            "platform": "Linux",
            "python_version": "3.11.0",
            "provider": "anthropic",
            "model": "claude-3-5-sonnet",
            **(fields or {}),
        },
    }


def _command_run(sid, name="repl", success=True, duration_s=1.0, exit_status=0):
    return {
        "type": "command_run",
        "timestamp": time.time(),
        "session_id": sid,
        "schema_version": 1,
        "fields": {
            "command_name": name,
            "mode": "interactive",
            "success": success,
            "duration_s": duration_s,
            "exit_status": exit_status,
        },
    }


def _crash(sid, fingerprint="abc123", error_class="ValueError", ts=None):
    return {
        "type": "error",
        "timestamp": ts if ts is not None else time.time(),
        "session_id": sid,
        "schema_version": 1,
        "fields": {
            "error_class": error_class,
            "fingerprint": fingerprint,
            "stacktrace": ["line1", "line2"],
        },
    }


def test_aggregate_empty(tmp_path):
    storage = _storage(tmp_path)
    agg = DailyAggregator(storage)
    today = utc_date(utc_now())
    summary = agg.aggregate(today)
    assert summary["sessions"] == 0
    assert summary["commands"] == 0
    assert summary["crashes"]["total"] == 0


def test_aggregate_counts_sessions_and_commands(tmp_path):
    storage = _storage(tmp_path)
    storage.append("events", _session_start("s1"))
    storage.append("events", _session_start("s2"))
    storage.append("events", _command_run("s1", name="repl"))
    storage.append("events", _command_run("s2", name="headless", success=False, exit_status=1))
    agg = DailyAggregator(storage)
    today = utc_date(utc_now())
    summary = agg.aggregate(today)
    assert summary["sessions"] == 2
    assert summary["commands"] == 2
    assert summary["top_commands"][0]["name"] in ("repl", "headless")
    assert summary["command_success"].get("repl", 0) == 1
    assert summary["command_failure"].get("headless", 0) == 1


def test_aggregate_collects_crashes(tmp_path):
    storage = _storage(tmp_path)
    storage.append("crashes", _crash("s1", fingerprint="deadbeef", error_class="RuntimeError"))
    storage.append("crashes", _crash("s1", fingerprint="deadbeef", error_class="RuntimeError"))
    storage.append("crashes", _crash("s2", fingerprint="1234abcd", error_class="ValueError"))
    agg = DailyAggregator(storage)
    today = utc_date(utc_now())
    summary = agg.aggregate(today)
    assert summary["crashes"]["total"] == 3
    top = {row["fingerprint"]: row for row in summary["crashes"]["top"]}
    assert top["deadbeef"]["count"] == 2
    assert top["deadbeef"]["error_class"] == "RuntimeError"


def test_aggregate_persists_to_summary_file(tmp_path):
    storage = _storage(tmp_path)
    storage.append("events", _session_start("s1"))
    agg = DailyAggregator(storage)
    today = utc_date(utc_now())
    summary = agg.aggregate(today)
    assert summary["date"] == today
    assert storage.read_latest_summary(today) == summary


def test_aggregate_today_if_stale_is_idempotent(tmp_path):
    storage = _storage(tmp_path)
    storage.append("events", _session_start("s1"))
    agg = DailyAggregator(storage)
    s1 = agg.aggregate_today_if_stale()
    s2 = agg.aggregate_today_if_stale()
    assert s1["sessions"] == s2["sessions"] == 1
    # Same date is reused; the disk file is unchanged in shape.
    assert s1["date"] == s2["date"]


def test_aggregate_tool_summary(tmp_path):
    storage = _storage(tmp_path)
    storage.append(
        "events",
        {
            "type": "tool_summary",
            "timestamp": time.time(),
            "session_id": "s1",
            "fields": {"tool_name": "bash", "success": True, "duration_s": 0.5},
        },
    )
    agg = DailyAggregator(storage)
    summary = agg.aggregate(utc_date(utc_now()))
    assert summary["tools"]["top"][0]["name"] == "bash"
    assert summary["tools"]["success"]["bash"] == 1


def test_aggregate_handles_payload_without_fields(tmp_path):
    storage = _storage(tmp_path)
    storage.append("events", {"type": "session_start", "timestamp": time.time(), "session_id": "s1"})
    agg = DailyAggregator(storage)
    summary = agg.aggregate(utc_date(utc_now()))
    assert summary["sessions"] == 1
