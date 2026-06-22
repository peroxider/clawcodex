"""Facade — services/pipe_ipc/permissions.py has been moved to clawcodex_ext.

Real implementation lives in
``clawcodex_ext.services.pipe_ipc.permissions``.  Existing
``from src.services.pipe_ipc.permissions import …`` call sites continue
to work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc.permissions`` directly.
"""

from clawcodex_ext.services.pipe_ipc.permissions import (  # noqa: F401
    PipePermissionForwarder,
)

__all__ = [
    "PipePermissionForwarder",
]
