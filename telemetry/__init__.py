"""Independent telemetry package.

Public surface (the only symbols business code should reach for):

* :func:`get_recorder`           — process-global, lazy, returns a real
  recorder or a no-op :class:`_NullRecorder` based on
  :attr:`TelemetryConfig.enabled`.
* :func:`record_session_start`   — fire-and-forget convenience wrappers
* :func:`record_session_end`
* :func:`record_command_run`
* :func:`record_error`
* :func:`record_tool_summary`
* :class:`TelemetryConfig`      — config dataclass + :func:`load_config`
* :class:`TelemetryEvent`        — event dataclass + :class:`EventType`
* :class:`AnalyticsTelemetrySink` — drop-in :class:`AnalyticsSink`
  that routes ``src.services.analytics`` events into the live
  recorder. Installed by :func:`install_analytics_bridge`.

Anything else is an implementation detail and may change between
minor releases.
"""

from __future__ import annotations

from .aggregator import DailyAggregator
from .bridge import (
    AnalyticsTelemetrySink,
    get_analytics_bridge,
    install_analytics_bridge,
)
from .config import (
    ReportingConfig,
    TelemetryConfig,
    load_config,
)
from .events import SCHEMA_VERSION, EventType, TelemetryEvent
from .fingerprint import compute_fingerprint
from .redaction import RedactionConfig, Redactor
from .reporters import (
    CompositeReporter,
    DryRunReporter,
    LocalFileReporter,
    Reporter,
)
from .storage import LocalJsonlStorage
from .version import __version__

__all__ = [
    "AnalyticsTelemetrySink",
    "CompositeReporter",
    "DailyAggregator",
    "DryRunReporter",
    "EventType",
    "LocalFileReporter",
    "LocalJsonlStorage",
    "RedactionConfig",
    "Redactor",
    "Reporter",
    "ReportingConfig",
    "SCHEMA_VERSION",
    "TelemetryConfig",
    "TelemetryEvent",
    "__version__",
    "compute_fingerprint",
    "get_analytics_bridge",
    "install_analytics_bridge",
    "load_config",
]


# ---------------------------------------------------------------------------
# Convenience wrappers around ``get_recorder()``
#
# These exist so that business code (CLI dispatch, headless, REPL) can call
# ``record_session_start(...)`` etc. directly without reaching into the
# recorder object. The wrappers are zero-cost when telemetry is disabled
# because they route through the null recorder's no-op methods.
# ---------------------------------------------------------------------------


def _recorder():  # private — internal callers
    from .recorder import get_recorder as _get

    return _get()


def record_session_start(**kwargs) -> None:
    """Forward ``kwargs`` to :meth:`_TelemetryRecorderImpl.record_session_start`."""
    _recorder().record_session_start(**kwargs)


def record_session_end(**kwargs) -> None:
    _recorder().record_session_end(**kwargs)


def record_command_run(**kwargs) -> None:
    _recorder().record_command_run(**kwargs)


def record_error(**kwargs) -> None:
    _recorder().record_error(**kwargs)


def record_tool_summary(**kwargs) -> None:
    _recorder().record_tool_summary(**kwargs)


def record_turn(**kwargs) -> None:
    _recorder().record_turn(**kwargs)


def record_usage(**kwargs) -> None:
    _recorder().record_usage(**kwargs)
