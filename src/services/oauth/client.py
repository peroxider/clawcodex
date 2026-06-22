"""Facade — services/oauth/client.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.oauth.client``.
Existing ``from src.services.oauth.client import …`` call sites continue
to work during the migration.  New code should import from
``clawcodex_ext.services.oauth.client`` directly.
"""

from clawcodex_ext.services.oauth.client import (  # noqa: F401
    get_organization_uuid,
)

__all__ = ["get_organization_uuid"]
