"""Local Session Visualizer.

A standalone web application for visualizing agent execution sessions
via Gantt charts, timelines, and performance analytics.
"""

from __future__ import annotations

__version__ = "0.1.0"

# F-REC: register the asciicast DashboardSource so the agent dashboard
# (TUI ``/dashboard`` command, visualizer web tab, DashboardList /
# DashboardGet tools) can pull from it. The source itself is a thin
# recording-only view; its primary caller is the ``clawcodex record``
# CLI which polls snapshots on a 1 Hz tick and renders them as ASCII
# panels. Registration is wrapped in try/except so the visualizer
# keeps loading even when extensions.recording is unavailable (e.g.
# partial checkout in CI smoke).
try:  # pragma: no cover - defensive
    from extensions.agent_dashboard import register_dashboard_source
    from extensions.visualizer.asciicast_dashboard_source import (
        AsciicastDashboardSource,
    )

    register_dashboard_source(AsciicastDashboardSource())
except Exception:
    pass
