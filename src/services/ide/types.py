"""Facade — src/services/ide/types.py has been moved to clawcodex_ext.

The full implementation now lives in :mod:`clawcodex_ext.services.ide.types`.
This module re-exports the public surface so existing
``from src.services.ide.types import ...`` call sites keep working without
modification.
"""

from __future__ import annotations

from clawcodex_ext.services.ide.types import (
    IDEConnection,
    IDEDiagnostic,
    IDEDiagnosticSeverity,
    IDERange,
    IDESelection,
    IDEType,
)

__all__ = [
    "IDEConnection",
    "IDEDiagnostic",
    "IDEDiagnosticSeverity",
    "IDERange",
    "IDESelection",
    "IDEType",
]
