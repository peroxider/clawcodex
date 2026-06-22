"""Facade — services/analytics/events.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.analytics.events``.
Existing ``from src.services.analytics.events import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.analytics.events`` directly.

The module-level ``_global_sink`` singleton lives in the canonical
``clawcodex_ext`` module; ``set_analytics_sink`` / ``get_analytics_sink``
/ ``log_event`` re-exported here operate on the same state, so callers
using either path see consistent behavior.
"""

from clawcodex_ext.services.analytics.events import (  # noqa: F401
    AnalyticsEvent,
    EventType,
    get_analytics_sink,
    log_event,
    set_analytics_sink,
)

__all__ = [
    "AnalyticsEvent",
    "EventType",
    "get_analytics_sink",
    "log_event",
    "set_analytics_sink",
]
