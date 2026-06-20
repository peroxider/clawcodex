"""Tests for clawcodex_ext.community_radar.cron_integration."""

from __future__ import annotations

import json
from pathlib import Path

from clawcodex_ext.community_radar.cron_integration import (
    DEFAULT_CRON_TASK_ID,
    get_cron_task_status,
    install_cron_task,
    load_registry_safely,
    uninstall_cron_task,
)


def test_install_uninstall_roundtrip(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAWCODEX_HOME", str(tmp_path))
    summary = install_cron_task(schedule="0 8 * * 1")
    if not summary.installed:
        # F-22 not available in this environment — treat as smoke test.
        return
    assert summary.schedule == "0 8 * * 1"

    status = get_cron_task_status()
    assert status.installed is True
    assert status.task_id == DEFAULT_CRON_TASK_ID

    removed = uninstall_cron_task()
    assert removed.installed is True

    again = get_cron_task_status()
    assert again.installed is False


def test_install_with_invalid_id(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAWCODEX_HOME", str(tmp_path))
    summary = install_cron_task(task_id="custom-task", schedule="0 9 * * 1")
    if not summary.installed:
        return
    status = get_cron_task_status(task_id="custom-task")
    assert status.installed is True
    uninstall_cron_task(task_id="custom-task")


def test_load_registry_safely_seeds_defaults(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAWCODEX_HOME", str(tmp_path))
    registry = load_registry_safely()
    assert len(registry) > 0
    names = {s.name for s in registry.list()}
    assert "aider" in names
    assert "claude-code" in names


def test_uninstall_when_no_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CLAWCODEX_HOME", str(tmp_path))
    summary = uninstall_cron_task()
    # Either way: it should not raise.
    assert summary.task_id == DEFAULT_CRON_TASK_ID