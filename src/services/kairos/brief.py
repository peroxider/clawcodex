"""Facade — src/services/kairos/brief.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos.brief`. This module re-exports the public surface so
existing ``from src.services.kairos.brief import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos.brief import (  # noqa: F401
    BriefSummaryBuilder,
)

__all__ = ['BriefSummaryBuilder']
