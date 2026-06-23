"""Facade — src/services/ide/ has been moved to clawcodex_ext.

The full implementation now lives in :mod:`clawcodex_ext.services.ide`.
This module re-exports the public surface so existing
``from src.services.ide import ...`` call sites keep working without
modification.
"""

from __future__ import annotations

from clawcodex_ext.services.ide import (
    DiagnosticsCollector,
    IDEConnection,
    IDEConnectionManager,
    IDEDiagnostic,
    IDEDiagnosticSeverity,
    IDERange,
    IDESelection,
    IDEType,
    SelectionTracker,
)

__all__ = [
    "DiagnosticsCollector",
    "IDEConnection",
    "IDEConnectionManager",
    "IDEDiagnostic",
    "IDEDiagnosticSeverity",
    "IDERange",
    "IDESelection",
    "IDEType",
    "SelectionTracker",
]
