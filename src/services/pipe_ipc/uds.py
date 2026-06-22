"""Facade — services/pipe_ipc/uds.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.pipe_ipc.uds``.
Existing ``from src.services.pipe_ipc.uds import …`` call sites continue
to work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc.uds`` directly.
"""

from clawcodex_ext.services.pipe_ipc.uds import (  # noqa: F401
    UdsPipeClient,
    UdsPipeServer,
)

__all__ = [
    "UdsPipeClient",
    "UdsPipeServer",
]
