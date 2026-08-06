"""End-to-end tests for F-REC-AUTO: ``extensions.recording.auto_demo``.

The :func:`auto_demo.run` entry point drives a real orchestrator batch
(success / verification_failed / pre_commit-hook) against a bare
``LocalTrackerAdapter`` + bare origin scaffold, and streams both:

* orchestrator markers via :class:`AsciicastSink` (one composite per
  issue, attached to the same shared capture handle)
* dashboard panel snapshots via :class:`AsciicastDashboardSource`
  (1Hz tick loop)

into one :class:`AsciicastWriter`. The tests below assert the .cast
file is valid, the markers are present in the expected order, and
the CLI ``record --auto`` subcommand reaches the same code path.

These tests are the regression net for F-REC-AUTO (the
deferred §1.8 entry). They run subprocess-free for the orchestration
parts (using :func:`asyncio.run` on the module's own coroutine) so
they stay fast; only ``test_auto_demo_cli_subprocess_auto_flag``
spawns the real CLI.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from extensions.capabilities.recorder import AsciicastHeader
from extensions.recording.asciicast_writer import AsciicastWriter
from extensions.recording.validate_cast import validate_cast


def _read_cast(path: Path) -> tuple[dict, list[list[object]]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    events = [json.loads(line) for line in raw[1:]]
    return header, events


def _markers(path: Path) -> list[str]:
    _, events = _read_cast(path)
    return [e[2] for e in events if e[1] == "m"]


def _frames(path: Path) -> list[list[object]]:
    _, events = _read_cast(path)
    return events


def test_auto_demo_imports_clean() -> None:
    """Top-level imports + public symbols resolve without side-effects."""
    from extensions.recording import auto_demo

    # Public API surface (matches ``__all__``).
    assert hasattr(auto_demo, "run")
    assert hasattr(auto_demo, "issues_for_auto_demo")
    assert hasattr(auto_demo, "build_parser")
    assert hasattr(auto_demo, "DASHBOARD_PULL_SOURCES")
    assert hasattr(auto_demo, "main")
    assert hasattr(auto_demo, "supports_auto")

    # Issues list is non-empty and well-formed.
    issues = auto_demo.issues_for_auto_demo()
    assert len(issues) >= 1
    for issue in issues:
        assert {"id", "identifier", "title"} <= issue.keys()


def test_auto_demo_run_short_duration_writes_valid_cast(tmp_path: Path) -> None:
    """``auto_demo.run`` writes a valid .cast even on a short budget."""
    from extensions.recording.auto_demo import run

    out_path = tmp_path / "auto.cast"
    rc = asyncio.run(
        run(
            out_path,
            duration_s=4.0,
            issue_count=1,
            frame_delay_s=0.5,
        )
    )
    assert rc == 0, "auto_demo.run returned non-zero on short budget"
    assert out_path.exists(), "auto_demo.run did not write the .cast"
    assert validate_cast(out_path) == [], "validate_cast reported errors"

    header, events = _read_cast(out_path)
    assert header["version"] == 2
    assert header["width"] == 120
    assert header["height"] == 36
    # 4 s budget / 0.5 s tick ≈ 8 panel ticks + 1 issue completion marker.
    # We assert only the lower bound so the test is not flaky when CI is
    # ~2x slower (CI env doesn't relax this assertion).
    assert len(events) >= 4


def test_auto_demo_records_orchestrator_phase_markers(tmp_path: Path) -> None:
    """Each issue emits at least one ``[phase N/T]`` + ``session:...`` marker."""
    from extensions.recording.auto_demo import run

    out_path = tmp_path / "auto-phases.cast"
    asyncio.run(
        run(
            out_path,
            duration_s=4.0,
            issue_count=1,
            frame_delay_s=0.5,
        )
    )

    markers = _markers(out_path)
    # Phase marker from the per-issue composite sink.
    phase_markers = [m for m in markers if m.startswith("[phase ")]
    assert len(phase_markers) >= 1, (
        f"expected at least one [phase N/T] marker; got markers={markers!r}"
    )
    # Session-complete marker is appended at the end of each sync.
    session_markers = [m for m in markers if m.startswith("session:")]
    assert len(session_markers) >= 1, (
        f"expected at least one session:... marker; got markers={markers!r}"
    )


def test_auto_demo_records_dashboard_panels_with_real_registry_entries(
    tmp_path: Path,
) -> None:
    """The dashboard tick frames are ASCII panels (output frames), not markers.

    The :class:`AsciicastDashboardSource` writes ``o`` (output) frames
    containing the rendered panel. We assert there is at least one such
    frame so the tick loop genuinely fed entries through the visualizer
    source rather than silently doing nothing.
    """
    from extensions.recording.auto_demo import run

    out_path = tmp_path / "auto-panels.cast"
    asyncio.run(
        run(
            out_path,
            duration_s=4.0,
            issue_count=1,
            frame_delay_s=0.5,
        )
    )

    events = _frames(out_path)
    output_frames = [e for e in events if e[1] == "o"]
    assert len(output_frames) >= 1, (
        "no output frames in .cast; dashboard tick loop did not emit panels"
    )
    # Panel payload should contain at least the canonical header line
    # the AsciicastDashboardSource writes. The exact string is
    # ``Logical Kanban (tick ...)`` — the demo uses this title template.
    concatenated = "\n".join(str(e[2]) for e in output_frames)
    assert "Logical Kanban" in concatenated, (
        "dashboard panels missing the expected title; "
        f"first output frame payload = {output_frames[0][2]!r}"
    )


def test_auto_demo_dashboard_source_pulls_all_registry_sources(tmp_path: Path) -> None:
    """``pull_dashboard_entries`` skips empty / failing sources but keeps good ones.

    The aggregator is the contract between the demo's tick loop and
    the rest of the registry — if it drops real entries or, worse,
    raises on a misbehaving source, the demo would emit blank panels.
    """
    from extensions.capabilities.dashboard_entry import (
        DASHBOARD_STATUS_PENDING,
        DashboardEntry,
    )
    from extensions.recording.auto_demo import (
        DASHBOARD_PULL_SOURCES,
        pull_dashboard_entries,
    )

    class _PullingSource:
        source_name = "orchestrator"

        def __init__(self, entries: list[DashboardEntry]) -> None:
            self._entries = entries

        def pull(self) -> list[DashboardEntry]:
            return list(self._entries)

    class _EmptySource:
        source_name = "orchestrator"

        def pull(self) -> list[DashboardEntry]:
            return []

    class _RaisingSource:
        source_name = "orchestrator"

        def pull(self) -> list[DashboardEntry]:
            raise RuntimeError("simulated dashboard pull failure")

    good = _PullingSource(
        [
            DashboardEntry(
                id="local:auto-1",
                source="local",
                title="AUTO-1",
                status=DASHBOARD_STATUS_PENDING,
                owner="auto_demo",
            )
        ]
    )
    empty = _EmptySource()
    raising = _RaisingSource()

    fallback = [
        DashboardEntry(
            id="synthetic",
            source="local",
            title="SYNTHETIC",
            status=DASHBOARD_STATUS_PENDING,
            owner="auto_demo",
        )
    ]

    # The aggregator should keep the fallback, the good source's entry,
    # skip the empty source's nothing, and skip the raising source's
    # exception. Order: fallback first, then good.
    aggregated = pull_dashboard_entries([good, empty, raising], fallback)
    assert len(aggregated) == 2
    assert aggregated[0].id == "synthetic"
    assert aggregated[1].id == "local:auto-1"

    # The allowed source name whitelist exists for a reason: any source
    # outside the whitelist must be ignored even if it pulls successfully.
    class _ForeignSource(_PullingSource):
        source_name = "unsupported"

    foreign = _ForeignSource(
        [
            DashboardEntry(
                id="foreign:1",
                source="foreign",
                title="FOREIGN",
                status=DASHBOARD_STATUS_PENDING,
                owner="x",
            )
        ]
    )
    aggregated = pull_dashboard_entries([foreign], fallback)
    assert [e.id for e in aggregated] == ["synthetic"], (
        "foreign source should be ignored even when pull() succeeds"
    )
    assert "orchestrator" in DASHBOARD_PULL_SOURCES


def test_auto_demo_cli_subprocess_auto_flag(tmp_path: Path) -> None:
    """``clawcodex-dev record --auto ...`` reaches ``auto_demo.run``.

    Spawns the real CLI as a subprocess so the subcommand registry +
    argparse plumbing are exercised end-to-end. The duration is kept
    short (3 s) so the test stays under CI timeouts.
    """
    cast_path = tmp_path / "cli-auto.cast"
    cmd = [
        sys.executable,
        "-m",
        "clawcodex_ext.cli.main",
        "record",
        "--auto",
        "--out",
        str(cast_path),
        "--auto-duration-s",
        "3",
        "--auto-issue-count",
        "1",
        "--auto-frame-delay-s",
        "0.5",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert result.returncode == 0, (
        f"CLI --auto failed (rc={result.returncode}); "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert cast_path.exists(), "CLI --auto did not produce a .cast file"
    assert validate_cast(cast_path) == [], (
        f"validate_cast failed on CLI --auto output: {validate_cast(cast_path)!r}"
    )

    markers = _markers(cast_path)
    assert any(m.startswith("[phase ") for m in markers), (
        f"CLI --auto .cast is missing phase markers: {markers!r}"
    )


def test_auto_demo_supports_auto_probe() -> None:
    """``supports_auto()`` returns True on this checkout (sanity)."""
    from extensions.recording.auto_demo import supports_auto

    assert supports_auto() is True, (
        "supports_auto() should return True on a checkout that ships "
        "extensions.agent_dashboard.sources.orchestrator_source"
    )


def test_auto_demo_run_rejects_bad_inputs(tmp_path: Path) -> None:
    """``auto_demo.run`` raises ValueError on out-of-range inputs.

    Guards against the adversarial probes the verification agent found:
    a negative ``frame_delay_s`` previously triggered a busy loop
    (~876 frames in 0.2 s); NaN / inf inputs silently passed argparse's
    ``type=float`` and reached :func:`asyncio.wait_for`.
    """
    from extensions.recording.auto_demo import run

    out_path = tmp_path / "bad-input.cast"

    # Negative frame delay used to spawn a busy loop.
    with pytest.raises(ValueError, match="frame_delay_s must be a positive"):
        asyncio.run(run(out_path, duration_s=1.0, frame_delay_s=-1.0))

    # Zero frame delay is also rejected — minimum useful cadence is > 0.
    with pytest.raises(ValueError, match="frame_delay_s must be a positive"):
        asyncio.run(run(out_path, duration_s=1.0, frame_delay_s=0.0))

    # NaN frame delay.
    with pytest.raises(ValueError, match="frame_delay_s must be a positive"):
        asyncio.run(run(out_path, duration_s=1.0, frame_delay_s=float("nan")))

    # Inf frame delay.
    with pytest.raises(ValueError, match="frame_delay_s must be a positive"):
        asyncio.run(run(out_path, duration_s=1.0, frame_delay_s=float("inf")))

    # Negative duration.
    with pytest.raises(ValueError, match="duration_s must be a non-negative"):
        asyncio.run(run(out_path, duration_s=-1.0, frame_delay_s=0.5))

    # NaN duration.
    with pytest.raises(ValueError, match="duration_s must be a non-negative"):
        asyncio.run(run(out_path, duration_s=float("nan"), frame_delay_s=0.5))

    # Zero issue count.
    with pytest.raises(ValueError, match="issue_count must be >= 1"):
        asyncio.run(run(out_path, duration_s=1.0, frame_delay_s=0.5, issue_count=0))

    # None of the failure paths should have left a stray .cast behind.
    assert not out_path.exists(), (
        f"bad-input run left {out_path} on disk; "
        "validation should reject before opening the writer"
    )


def test_auto_demo_cli_rejects_bad_inputs(tmp_path: Path) -> None:
    """The CLI argparse types reject negative / non-finite --auto-* values.

    These rejections happen before ``run()`` is reached, so the test
    asserts on the CLI's exit code + stderr rather than the cast file.
    """
    cmd = [
        sys.executable,
        "-m",
        "clawcodex_ext.cli.main",
        "record",
        "--auto",
        "--out",
        str(tmp_path / "should-not-exist.cast"),
        "--auto-duration-s",
        "2",
        "--auto-issue-count",
        "1",
        "--auto-frame-delay-s",
        "-1",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert result.returncode != 0, (
        "CLI accepted a negative --auto-frame-delay-s; busy-loop regression"
    )
    assert "positive finite" in result.stderr or "positive" in result.stderr, (
        f"CLI rejection message missing; stderr={result.stderr!r}"
    )
    assert not (tmp_path / "should-not-exist.cast").exists(), (
        "CLI rejected the input but still wrote a .cast file"
    )