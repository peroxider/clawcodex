"""Visualizer dashboard adapter for asciicast recording (F-REC).

The visualizer is normally a *consumer* of NDJSON transcripts. To
record what its dashboard panels look like, this module implements
:class:`DashboardSource` (the protocol from
``extensions/capabilities/dashboard_entry.py:120``) and renders each
``pull()`` snapshot as ASCII tables.

When registered into the existing ``DashboardSourceRegistry`` the
adapter also exposes a separate method, :meth:`record_snapshot`, that
takes a capture handle and writes one or more ``o`` frames containing
the rendered panels. The :class:`extensions.recording.cli` module
calls :meth:`record_snapshot` on a 1-second tick to produce a
``tail -f`` style recording of the dashboard.
"""

from __future__ import annotations

import logging
from typing import Any

from extensions.capabilities.dashboard_entry import (
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSource,
    normalize_source_name,
)
from extensions.capabilities.recorder import (
    AsciicastCapture,
    AsciicastEvent,
)
from extensions.recording.renderers import panel

logger = logging.getLogger(__name__)


_STATUS_BADGE = {
    "pending": "⏳ pending",
    "in_progress": "🔵 running",
    "completed": "✅ done",
    "failed": "❌ failed",
    "blocked": "🚧 blocked",
}


class AsciicastDashboardSource:
    """A :class:`DashboardSource` that renders snapshots to ASCII panels.

    The adapter is registered into the
    :class:`extensions.agent_dashboard.source_registry.DashboardSourceRegistry`
    under the name ``"visualizer_asciicast"`` and is independent from
    the live HTML visualizer — it pulls from the same DashboardSource
    implementations but produces text instead of HTML.
    """

    source_name = "visualizer_asciicast"

    def __init__(self) -> None:
        # The adapter wraps the underlying DashboardSource list at
        # record time — there's no need to hold references at
        # construction time, which keeps this class trivial to test.
        pass

    def pull(self, **filters: Any) -> list[DashboardEntry]:
        """Return an empty snapshot.

        The asciicast adapter is a recording-only view of the
        dashboard; it doesn't participate in the normal pull path that
        powers the Web UI / TUI dashboard command. ``pull`` is still
        implemented (per the :class:`DashboardSource` Protocol) so the
        adapter registers cleanly into the source registry.
        """
        return []

    @property
    def cache_ttl_ms(self) -> int:
        # 1 second — same cadence the recording tick uses. The
        # recording CLI ignores this value (it calls record_snapshot
        # directly) but a downstream consumer reading via
        # DashboardStore would see a reasonable cache lifetime.
        return 1000

    # -- recording-specific surface ------------------------------------

    def record_snapshot(
        self,
        capture: AsciicastCapture,
        entries: list[DashboardEntry],
        *,
        title: str = "Dashboard",
    ) -> None:
        """Render ``entries`` into the capture as ASCII panel frames.

        One ``marker`` per status group plus one ``o`` frame per panel.
        Designed to be called from a 1 Hz tick inside the recording
        CLI.
        """
        try:
            capture.marker("dashboard:snapshot", text=f"{title} snapshot")
            for frame in _render_panels(entries, title=title):
                capture.emit(AsciicastEvent(t=0.0, kind="o", data=frame + "\n"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("record_snapshot failed: %s", exc)


def _render_panels(
    entries: list[DashboardEntry],
    *,
    title: str,
    width: int = 80,
) -> list[str]:
    """Group entries by status and render one panel per group.

    Mirrors the HTML panel layout in
    ``extensions/visualizer/templates/orchestrator_dashboard.html``
    (stat-card grid + issue table) using ``─`` rules and indented rows.
    """
    if not entries:
        return [panel(title, ["(no entries)"], width=width)]

    by_status: dict[str, list[DashboardEntry]] = {s: [] for s in _STATUS_BADGE}
    for entry in entries:
        status = entry.status if entry.status in DASHBOARD_STATUSES else "pending"
        by_status.setdefault(status, []).append(entry)

    panels: list[str] = []

    # Summary stat-card row
    stats_line = "  " + "  ".join(
        f"{_STATUS_BADGE[status]}: {len(by_status.get(status, []))}"
        for status in _STATUS_BADGE
    )
    panels.append(panel(title, [stats_line], width=width))

    # Per-status detail rows (active statuses only)
    for status, label in _STATUS_BADGE.items():
        group = by_status.get(status, [])
        if not group:
            continue
        rows = [f"  {label}  ({len(group)})"]
        for entry in group[:8]:  # cap per-panel rows for legibility
            title_col = entry.title[:48] if entry.title else "(untitled)"
            detail = f"  • {entry.id:<20} {title_col:<48} {_pct(entry.progress_pct)}"
            rows.append(detail)
        if len(group) > 8:
            rows.append(f"  … and {len(group) - 8} more")
        panels.append(panel(f"{title} — {label}", rows, width=width))

    return panels


def _pct(p: float | None) -> str:
    if p is None:
        return ""
    return f"{int(round(p * 100))}%"


__all__ = ["AsciicastDashboardSource"]