"""Facade — services/oauth/__init__.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.oauth``.  Existing
``from src.services.oauth import …`` call sites continue to work during
the migration.  New code should import from
``clawcodex_ext.services.oauth`` directly.
"""

from clawcodex_ext.services.oauth import (  # noqa: F401
    get_organization_uuid,
)

__all__ = ["get_organization_uuid"]
