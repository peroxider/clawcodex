"""Facade — src/services/kairos/exceptions.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos.exceptions`. This module re-exports the public surface so
existing ``from src.services.kairos.exceptions import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos.exceptions import (  # noqa: F401
    KairosError,
    TickConfigError,
    SchedulerStateError,
    DailyLogError,
    BriefGenerationError,
)

__all__ = ['KairosError', 'TickConfigError', 'SchedulerStateError', 'DailyLogError', 'BriefGenerationError']
