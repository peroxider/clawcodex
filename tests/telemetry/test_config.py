"""Tests for TelemetryConfig + load_config()."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from clawcodex.telemetry.config import (
    ReportingConfig,
    TelemetryConfig,
    load_config,
)
from clawcodex.telemetry.redaction import RedactionConfig


def test_default_config_is_disabled():
    cfg = TelemetryConfig()
    assert cfg.enabled is False
    assert cfg.reporting.reporting_enabled is False
    assert cfg.reporting.kind == "local_file"
    assert cfg.retention_days == 30
    assert isinstance(cfg.redaction, RedactionConfig)
    assert cfg.redaction.include_prompts is False
    assert cfg.redaction.include_outputs is False


def test_load_config_defaults_when_nothing_set(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAW_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("CLAW_TELEMETRY_REPORTING_ENABLED", raising=False)
    monkeypatch.delenv("CLAW_TELEMETRY_STORAGE_DIR", raising=False)
    cfg = load_config()
    assert cfg.enabled is False
    assert cfg.reporting.reporting_enabled is False


def test_env_override_enables_collection(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAW_TELEMETRY_ENABLED", "1")
    cfg = load_config()
    assert cfg.enabled is True


def test_env_override_enables_reporting(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAW_TELEMETRY_ENABLED", "1")
    monkeypatch.setenv("CLAW_TELEMETRY_REPORTING_ENABLED", "1")
    cfg = load_config()
    assert cfg.enabled is True
    assert cfg.reporting.reporting_enabled is True


def test_env_storage_dir_expansion(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "telemetry-store"
    monkeypatch.setenv("CLAW_TELEMETRY_STORAGE_DIR", str(target))
    cfg = load_config()
    assert cfg.storage_dir == target.expanduser()


def test_reporting_kind_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAW_TELEMETRY_ENABLED", "1")
    cfg = load_config()
    assert cfg.reporting.kind == "local_file"


def test_config_dataclass_is_frozen():
    cfg = TelemetryConfig()
    with pytest.raises(Exception):
        cfg.enabled = True  # type: ignore[misc]


def test_reporting_config_defaults():
    rc = ReportingConfig()
    assert rc.reporting_enabled is False
    assert rc.kind == "local_file"
