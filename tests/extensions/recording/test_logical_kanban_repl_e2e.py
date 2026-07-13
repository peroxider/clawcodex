"""End-to-end subprocess test for the logical kanban REPL demo.

Runs :mod:`extensions.recording.examples.logical_kanban_repl_demo` as a
fresh subprocess and verifies the produced ``.cast`` file is valid +
contains the expected kanban progression (tick 0 → tick 3). This is
the only "user-facing demo" test for F-REC — it exercises the example
end-to-end exactly the way a developer running ``python -m
extensions.recording.examples.logical_kanban_repl_demo`` would.

Why a subprocess (not an in-process call):

* proves the example works as a standalone entry point (not just as
  an import side-effect);
* protects against regressions where someone refactors the example to
  import private symbols from ``extensions.recording.*`` and breaks
  the ``python -m`` invocation;
* keeps the test honest — it can't rely on test fixtures that
  wouldn't exist in production.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from extensions.recording.validate_cast import validate_cast


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_MODULE = "extensions.recording.examples.logical_kanban_repl_demo"


def _run_demo(tmp_path: Path, *, ticks: int = 4, delay: float = 0.05) -> Path:
    out = tmp_path / "kanban.cast"
    cmd = [
        sys.executable,
        "-m",
        EXAMPLE_MODULE,
        "--out",
        str(out),
        "--ticks",
        str(ticks),
        "--frame-delay",
        str(delay),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"demo exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert out.exists(), f"expected {out} to exist"
    assert out.stat().st_size > 0, f"{out} is empty"
    return out


def _frames(path: Path) -> tuple[dict, list[list[object]]]:
    raw = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(raw[0])
    events = [json.loads(line) for line in raw[1:]]
    return header, events


def test_demo_produces_valid_cast_file(tmp_path: Path) -> None:
    cast = _run_demo(tmp_path, ticks=4, delay=0.05)
    errors = validate_cast(cast)
    assert errors == [], errors


def test_demo_header_metadata_is_set(tmp_path: Path) -> None:
    cast = _run_demo(tmp_path, ticks=2, delay=0.05)
    header, _ = _frames(cast)
    assert header["version"] == 2
    assert header["width"] == 120
    assert header["height"] == 36
    # Header title reflects the REPL session context, not the per-tick
    # panel title — the example sets the header title once and lets
    # record_snapshot override the *panel* title each tick.
    assert header["title"] == "ClawCodex REPL — /dashboard for orchestrator run"
    assert header["command"] == "clawcodex record --sources visualizer --out demo.cast"


def test_demo_records_one_marker_per_tick(tmp_path: Path) -> None:
    cast = _run_demo(tmp_path, ticks=4, delay=0.05)
    _, events = _frames(cast)
    markers = [e[2] for e in events if e[1] == "m"]
    assert markers == ["dashboard:snapshot"] * 4


def test_demo_timestamps_are_monotonic_across_ticks(tmp_path: Path) -> None:
    """Each snapshot tick must come AFTER the previous one in writer time."""
    cast = _run_demo(tmp_path, ticks=4, delay=0.1)
    _, events = _frames(cast)
    snapshot_times: list[float] = []
    for event in events:
        if event[1] == "m" and event[2] == "dashboard:snapshot":
            snapshot_times.append(event[0])
    assert len(snapshot_times) == 4
    assert snapshot_times == sorted(snapshot_times)
    # At minimum, the gap between consecutive ticks should reflect the
    # --frame-delay we passed in (≥ 0.1s - small scheduler noise).
    gaps = [
        snapshot_times[i + 1] - snapshot_times[i]
        for i in range(len(snapshot_times) - 1)
    ]
    for gap in gaps:
        assert gap >= 0.05, f"gap too small: {gap}"


def test_demo_renders_status_progression_in_panels(tmp_path: Path) -> None:
    """Verify the rendered panels contain the entries we expect per tick.

    The demo deliberately advances entries from
    pending/in_progress/completed → completed/failed → blocked across
    4 ticks. We assert that each tick's panel output reflects the
    intended transition (e.g. tick 2 should show ✅ done: 2 and
    ❌ failed: 1).
    """
    cast = _run_demo(tmp_path, ticks=4, delay=0.05)
    _, events = _frames(cast)
    outputs = [e[2] for e in events if e[1] == "o"]

    # Concatenate so cross-frame text matches are easier.
    full = "\n".join(outputs)

    # Tick 0: stats line shows 1 pending, 2 running, 0 done.
    assert "⏳ pending: 1" in full
    assert "🔵 running: 2" in full
    assert "✅ done: 0" in full

    # Tick 1: 1 done (the first issue finished).
    assert "✅ done: 1" in full

    # Tick 2: 2 done, 1 failed (the queue unblocks).
    assert "✅ done: 2" in full
    assert "❌ failed: 1" in full

    # Tick 3: 1 blocked (waiting on a decision) + 1 new pending entry.
    assert "🚧 blocked: 1" in full
    assert "gh:45" in full  # the follow-up issue

    # Each tick's panel header uses the demo's per-tick title.
    assert "Logical Kanban (tick 0)" in full
    assert "Logical Kanban (tick 3)" in full


def test_demo_uses_only_public_frec_apis(tmp_path: Path) -> None:
    """Sanity check: the example's source imports only public F-REC symbols.

    Catches accidental regressions where a future refactor starts
    importing private helpers (``extensions.recording._factories``,
    ``asciicast_writer._write_frame`` etc.) that wouldn't exist in a
    shipped wheel. We grep the source rather than introspect at
    runtime because import-time vs runtime visibility differs.
    """
    example_path = (
        REPO_ROOT
        / "extensions"
        / "recording"
        / "examples"
        / "logical_kanban_repl_demo.py"
    )
    text = example_path.read_text(encoding="utf-8")
    forbidden = [
        "_factories",
        "_write_frame",
        "asciicast_writer.AsciicastCaptureImpl",
    ]
    for token in forbidden:
        assert token not in text, (
            f"example imports private F-REC symbol {token!r}; "
            "use the public Protocol/writer surface only"
        )