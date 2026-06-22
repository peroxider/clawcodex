"""Facade — src/services/kairos/scheduler.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos.scheduler`. This module re-exports the public surface so
existing ``from src.services.kairos.scheduler import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos.scheduler import (  # noqa: F401
    TickScheduler,
)

__all__ = ['TickScheduler']
