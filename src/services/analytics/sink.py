"""Facade — services/analytics/sink.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.analytics.sink``.
Existing ``from src.services.analytics.sink import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.analytics.sink`` directly.
"""

from clawcodex_ext.services.analytics.sink import (  # noqa: F401
    AnalyticsSink,
    ConsoleSink,
    FileSink,
    NullSink,
)

__all__ = [
    "AnalyticsSink",
    "ConsoleSink",
    "FileSink",
    "NullSink",
]
