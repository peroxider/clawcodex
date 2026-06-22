"""Facade — services/periodic/__init__.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.periodic``.
Existing ``from src.services.periodic import …`` call sites continue to
work during the migration.  New code should import from
``clawcodex_ext.services.periodic`` directly.
"""

from clawcodex_ext.services.periodic import (  # noqa: F401
    PeriodicDaemon,
)

__all__ = [
    "PeriodicDaemon",
]
