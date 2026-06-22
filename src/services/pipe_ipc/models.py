"""Facade — services/pipe_ipc/models.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.pipe_ipc.models``.
Existing ``from src.services.pipe_ipc.models import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc.models`` directly.
"""

from clawcodex_ext.services.pipe_ipc.models import (  # noqa: F401
    PipeMessage,
    PipeMessageType,
    PipePeer,
)

__all__ = [
    "PipeMessage",
    "PipeMessageType",
    "PipePeer",
]
