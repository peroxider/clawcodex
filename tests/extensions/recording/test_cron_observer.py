"""Tests for the cron asciicast observer (F-REC)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from clawcodex_ext.cron_system.asciicast_observer import (
    AsciicastCronObserver,
    make_cron_observer,
    null_observer,
)


class _FakeTask:
    def __init__(self, task_id: str = "t-1", cron: str = "*/5 * * * *") -> None:
        self.id = task_id
        self.cron = cron


class _FakeRun:
    def __init__(self, run_id: str = "r-1") -> None:
        self.id = run_id


def _open_writer(tmp_path: Path) -> AsciicastWriter:
    writer = AsciicastWriter(
        tmp_path / "demo.cast",
        AsciicastHeader(width=120, height=36),
    )
    writer.open()
    return writer


def _markers(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)[2] for line in raw[1:] if json.loads(line)[1] == "m"]


def test_on_fire_task_marker_uses_task_id(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = AsciicastCronObserver(writer.capture)
    obs.on_fire_task(_FakeTask("backups"), _FakeRun("run-7"))
    writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert markers == ["cron:fire:backups"]


def test_on_missed_marker_lists_all_task_ids(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = AsciicastCronObserver(writer.capture)
    obs.on_missed([_FakeTask("a"), _FakeTask("b")], notification="expired slot")
    writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert markers == ["cron:missed:a,b"]


def test_on_fire_event_marker_uses_status(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = AsciicastCronObserver(writer.capture)
    obs.on_fire_event({"status": "fired", "task_id": "cleanup"})
    writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert markers == ["cron:event:fired"]


def test_on_expired_event_marker_uses_task_id(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = AsciicastCronObserver(writer.capture)
    obs.on_expired_event({"task_id": "stale", "status": "expired"})
    writer.close()

    markers = _markers(tmp_path / "demo.cast")
    assert markers == ["cron:expired:stale"]


def test_observer_swallows_non_dict_payload(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = AsciicastCronObserver(writer.capture)
    obs.on_fire_event("not a dict")  # type: ignore[arg-type]
    obs.on_expired_event(42)  # type: ignore[arg-type]
    writer.close()
    # No frames beyond the header.
    raw = (tmp_path / "demo.cast").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 1


def test_make_cron_observer_factory_returns_bound_observer(tmp_path: Path) -> None:
    writer = _open_writer(tmp_path)
    obs = make_cron_observer(writer.capture)
    obs.on_fire_task(_FakeTask("via-factory"), _FakeRun())
    writer.close()
    markers = _markers(tmp_path / "demo.cast")
    assert markers == ["cron:fire:via-factory"]


def test_null_observer_is_silent() -> None:
    """The no-op observer must accept the same callback signatures."""
    obs = null_observer()
    obs.on_fire_task(_FakeTask(), _FakeRun())
    obs.on_missed([_FakeTask()], notification="x")
    obs.on_fire_event({"status": "fired"})
    obs.on_expired_event({"task_id": "x"})