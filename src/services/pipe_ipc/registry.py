"""Facade — services/pipe_ipc/registry.py has been moved to clawcodex_ext.

Real implementation lives in ``clawcodex_ext.services.pipe_ipc.registry``.
Existing ``from src.services.pipe_ipc.registry import …`` call sites
continue to work during the migration.  New code should import from
``clawcodex_ext.services.pipe_ipc.registry`` directly.
"""

from clawcodex_ext.services.pipe_ipc.registry import (  # noqa: F401
    PipeRegistry,
)

__all__ = [
    "PipeRegistry",
]
