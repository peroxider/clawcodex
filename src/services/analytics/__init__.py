"""Facade — services/analytics/__init__.py has been moved to clawcodex_ext.

Real implementations live in ``clawcodex_ext.services.analytics``.
Existing ``from src.services.analytics import …`` call sites continue to
work during the migration.  New code should import from
``clawcodex_ext.services.analytics`` directly.
"""

from clawcodex_ext.services.analytics import (  # noqa: F401
    AnalyticsEvent,
    AnalyticsSink,
    ConsoleSink,
    EventType,
    FileSink,
    NullSink,
    SessionAnalyticsMetadata,
    collect_session_metadata,
    get_analytics_sink,
    log_event,
    set_analytics_sink,
)

__all__ = [
    "AnalyticsEvent",
    "AnalyticsSink",
    "ConsoleSink",
    "EventType",
    "FileSink",
    "NullSink",
    "SessionAnalyticsMetadata",
    "collect_session_metadata",
    "get_analytics_sink",
    "log_event",
    "set_analytics_sink",
]
