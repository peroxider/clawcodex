"""Facade — src/services/kairos/models.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos.models`. This module re-exports the public surface so
existing ``from src.services.kairos.models import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos.models import (  # noqa: F401
    TickConfig,
    TickEvent,
    BriefSummarySnapshot,
    DailyLogEntry,
    format_local_timestamp,
)

__all__ = ['TickConfig', 'TickEvent', 'BriefSummarySnapshot', 'DailyLogEntry', 'format_local_timestamp']
