"""Facade — src/services/kairos/daily_log.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos.daily_log`. This module re-exports the public surface so
existing ``from src.services.kairos.daily_log import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos.daily_log import (  # noqa: F401
    DailyLogWriter,
)

__all__ = ['DailyLogWriter']
