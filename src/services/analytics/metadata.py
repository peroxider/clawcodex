"""Facade — services/analytics/metadata.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.analytics.metadata``.
Existing ``from src.services.analytics.metadata import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.analytics.metadata`` directly.
"""

from clawcodex_ext.services.analytics.metadata import (  # noqa: F401
    SessionAnalyticsMetadata,
    collect_session_metadata,
)

__all__ = [
    "SessionAnalyticsMetadata",
    "collect_session_metadata",
]
