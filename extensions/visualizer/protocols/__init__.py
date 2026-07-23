"""F-167-A/B: combined Protocol surface for the visualizer package.

Both modules are *local copies* of the corresponding
``extensions.capabilities`` modules; see ``dashboard.py`` and
``recorder.py`` for the drift-tracking rationale.
"""

from __future__ import annotations

from extensions.visualizer.protocols.dashboard import (
    DASHBOARD_STATUS_BLOCKED,
    DASHBOARD_STATUS_COMPLETED,
    DASHBOARD_STATUS_FAILED,
    DASHBOARD_STATUS_IN_PROGRESS,
    DASHBOARD_STATUS_PENDING,
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSink,
    DashboardSource,
    filter_entries,
    normalize_source_name,
)
from extensions.visualizer.protocols.recorder import (
    AsciicastCapture,
    AsciicastEvent,
    AsciicastHeader,
    RecordableSource,
)

__all__ = [
    "DASHBOARD_STATUS_BLOCKED",
    "DASHBOARD_STATUS_COMPLETED",
    "DASHBOARD_STATUS_FAILED",
    "DASHBOARD_STATUS_IN_PROGRESS",
    "DASHBOARD_STATUS_PENDING",
    "DASHBOARD_STATUSES",
    "AsciicastCapture",
    "AsciicastEvent",
    "AsciicastHeader",
    "DashboardEntry",
    "DashboardSink",
    "DashboardSource",
    "RecordableSource",
    "filter_entries",
    "normalize_source_name",
]