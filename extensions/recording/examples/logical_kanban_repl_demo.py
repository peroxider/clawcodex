"""End-to-end example: REPL 中录制「逻辑看板」（逻辑看板）的实时更新。

Scenario: a developer is using ClawCodex REPL with the visualizer
dashboard open (``/dashboard`` command). They start an orchestrator run
on a batch of GitHub issues, and watch the logical kanban update over
time. This script reproduces that scenario headlessly and writes the
result to an asciicast v2 ``.cast`` file that can be replayed in a
browser via the asciinema player.

The script uses *only public F-REC APIs*:

* :class:`AsciicastHeader` — JSON header written as line 1
* :class:`AsciicastWriter`  — owns the .cast file (per-frame flush)
* :class:`AsciicastDashboardSource` — pulls DashboardEntry snapshots
  and renders them as ASCII panels (the same vocabulary the live
  visualizer uses for its HTML dashboards)

The script is intentionally short and self-contained so it doubles as
a runnable example (``python -m extensions.recording.examples.logical_kanban_repl_demo``)
and as a subprocess E2E test
(``tests/extensions/recording/test_logical_kanban_repl_e2e.py``).

Layer rule (CLAUDE.md): this file lives in Layer 2 alongside the
recorder package and is independent from ``src/`` / ``clawcodex_ext/``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Allow ``python extensions/recording/examples/logical_kanban_repl_demo.py``
# from a fresh checkout without requiring the package to be installed.
_PKG_PARENT = Path(__file__).resolve().parents[3]
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from extensions.capabilities.dashboard_entry import (  # noqa: E402
    DASHBOARD_STATUS_BLOCKED,
    DASHBOARD_STATUS_COMPLETED,
    DASHBOARD_STATUS_FAILED,
    DASHBOARD_STATUS_IN_PROGRESS,
    DASHBOARD_STATUS_PENDING,
    DashboardEntry,
)
from extensions.capabilities.recorder import AsciicastHeader  # noqa: E402
from extensions.recording.asciicast_writer import AsciicastWriter  # noqa: E402
from extensions.recording.validate_cast import validate_cast  # noqa: E402
from extensions.visualizer.asciicast_dashboard_source import (  # noqa: E402
    AsciicastDashboardSource,
)


def _initial_entries() -> list[DashboardEntry]:
    """Three issues being picked up by the orchestrator on tick 0."""
    return [
        DashboardEntry(
            id="gh:42",
            source="orchestrator",
            title="fix flaky test in cron scheduler",
            status=DASHBOARD_STATUS_IN_PROGRESS,
            progress_pct=0.0,
            owner="chad",
        ),
        DashboardEntry(
            id="gh:43",
            source="orchestrator",
            title="add F-REC asciicast recorder",
            status=DASHBOARD_STATUS_IN_PROGRESS,
            progress_pct=0.6,
            owner="chad",
        ),
        DashboardEntry(
            id="gh:44",
            source="orchestrator",
            title="upgrade dashboard panel template",
            status=DASHBOARD_STATUS_PENDING,
            owner="chad",
        ),
    ]


def _tick_progression(
    entries: list[DashboardEntry],
    tick: int,
) -> list[DashboardEntry]:
    """Advance entries one tick — simulates the orchestrator's progress.

    ``DashboardEntry`` is a frozen dataclass so the progression has to
    rebuild the touched entries via :func:`dataclasses.replace`. This
    matches how a real :class:`DashboardSource` would re-emit entries
    on its next ``pull()``.

    Tick 0: 3 in-flight (1 starting, 1 mid, 1 queued)
    Tick 1: 1 done, 1 advanced, 1 still pending
    Tick 2: 1 done, 1 done, 1 failed (the queue unblocks)
    Tick 3: 1 done, 1 done, 1 blocked (waiting on a decision) +
            a new follow-up issue appears
    """
    from dataclasses import replace

    if tick == 1:
        entries[0] = replace(
            entries[0],
            status=DASHBOARD_STATUS_COMPLETED,
            progress_pct=1.0,
        )
        entries[1] = replace(entries[1], progress_pct=0.85)
    elif tick == 2:
        entries[1] = replace(
            entries[1],
            status=DASHBOARD_STATUS_COMPLETED,
            progress_pct=1.0,
        )
        entries[2] = replace(entries[2], status=DASHBOARD_STATUS_FAILED)
    elif tick == 3:
        entries[2] = replace(entries[2], status=DASHBOARD_STATUS_BLOCKED)
        # A new follow-up entry just appeared in the orchestrator queue.
        entries.append(
            DashboardEntry(
                id="gh:45",
                source="orchestrator",
                title="write docs for F-REC",
                status=DASHBOARD_STATUS_PENDING,
                owner="chad",
            )
        )
    return entries


def run(out_path: Path, *, ticks: int = 4, frame_delay_s: float = 0.5) -> int:
    """Drive the example end-to-end. Returns the process exit code."""
    writer = AsciicastWriter(
        out_path,
        AsciicastHeader(
            width=120,
            height=36,
            title="ClawCodex REPL — /dashboard for orchestrator run",
            command="clawcodex record --sources visualizer --out demo.cast",
        ),
    )
    capture = writer.open()
    source = AsciicastDashboardSource()

    try:
        entries = _initial_entries()
        for tick in range(ticks):
            # The live visualizer would have just pulled from its
            # backing DashboardSource; we mirror that here by mutating
            # the in-memory snapshot before rendering.
            entries = _tick_progression(entries, tick)
            source.record_snapshot(
                capture, entries, title=f"Logical Kanban (tick {tick})"
            )
            if tick < ticks - 1:
                # Real wall-clock gap so timestamps are visibly spaced
                # apart when replayed (and so a `tail -f` reader sees
                # frames trickle in).
                time.sleep(frame_delay_s)
    finally:
        writer.close()

    # Self-check the output so a copy-paste run gives the user immediate
    # feedback on whether the .cast is structurally valid.
    errors = validate_cast(out_path)
    if errors:
        print(f"[demo] validation FAILED for {out_path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"[demo] {out_path} — {writer.frame_count} frame(s); "
        f"validation: OK"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="logical-kanban-repl-demo",
        description=(
            "End-to-end example: simulate a REPL /dashboard session and "
            "write an asciicast v2 .cast capturing the kanban tick "
            "sequence. Runnable as a standalone script or as a "
            "subprocess E2E test."
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("logical-kanban-demo.cast"),
        help="Output .cast file path (default: %(default)s).",
    )
    p.add_argument(
        "--ticks",
        type=int,
        default=4,
        help="Number of dashboard ticks to record (default: %(default)s).",
    )
    p.add_argument(
        "--frame-delay",
        type=float,
        default=0.5,
        help="Wall-clock seconds between ticks (default: %(default)s).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run(args.out, ticks=args.ticks, frame_delay_s=args.frame_delay)


if __name__ == "__main__":
    raise SystemExit(main())