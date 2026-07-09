"""F-120 Agent Dashboard — cross-system read-only aggregator.

The agent_dashboard package provides a unified, read-only view of
progress data from all agent-loop subsystems (goal, task,
orchestrator, SOP). It is the data layer only — no rendering happens
here. Consumers (TUI ``/dashboard`` command, Visualizer Web tab,
model tools ``DashboardList``/``DashboardGet``) read from the
``DashboardStore`` singleton and decide how to display the data.

Public surface:
  * :class:`DashboardStore` — the aggregate store.
  * :class:`DashboardSourceRegistry` — the source registration
    mechanism (re-exported from ``source_registry`` for convenience).
  * Sources: :class:`GoalDashboardSource`,
    :class:`TasksDashboardSource`.

The store is intentionally kept process-singleton: there is one
in-flight "view of the world" at any given moment per Python
process. Tests can instantiate their own store; production code
should use :func:`get_default_store` so the Visualizer WebSocket
and TUI see the same data.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from extensions.capabilities.dashboard_entry import (
    DASHBOARD_STATUSES,
    DashboardEntry,
    DashboardSink,
    DashboardSource,
    filter_entries,
    normalize_source_name,
)

from .source_registry import (
    DashboardSourceRegistry,
    get_default_registry,
    register_dashboard_source,
    unregister_dashboard_source,
)
from .store import DashboardStore, get_default_store

__all__ = [
    "DASHBOARD_STATUSES",
    "DashboardEntry",
    "DashboardSink",
    "DashboardSource",
    "DashboardSourceRegistry",
    "DashboardStore",
    "filter_entries",
    "get_default_registry",
    "get_default_store",
    "normalize_source_name",
    "register_dashboard_source",
    "unregister_dashboard_source",
]


def dashboard_archive_dir(*, home: Optional[Path] = None) -> Path:
    """Return the NDJSON archive directory (``~/.clawcodex/dashboard/``).

    NDJSON files live under this directory, one per source
    (``goal.ndjson`` / ``task.ndjson`` / ...). The path is overridable
    via the ``CLAWCODEX_DASHBOARD_HOME`` env var so tests can
    redirect to a tmp dir.
    """
    env_dir = os.environ.get("CLAWCODEX_DASHBOARD_HOME")
    if env_dir:
        return Path(env_dir).expanduser()
    if home is not None:
        return home / ".clawcodex" / "dashboard"
    return Path.home() / ".clawcodex" / "dashboard"


_DEFAULT_STORE: Optional[DashboardStore] = None
_DEFAULT_STORE_LOCK = threading.Lock()


def get_or_create_default_store() -> DashboardStore:
    """Lazy singleton accessor for the runtime :class:`DashboardStore`.

    Tests should construct their own :class:`DashboardStore` directly
    so they never race with the process-wide singleton.
    """
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = DashboardStore(archive_dir=dashboard_archive_dir())
        return _DEFAULT_STORE


def reset_default_store() -> None:
    """Drop the cached singleton. Test-only helper."""
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = None
