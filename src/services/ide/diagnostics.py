"""Facade — src/services/ide/diagnostics.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.ide.diagnostics`. This module re-exports the
public surface so existing ``from src.services.ide.diagnostics import ...``
call sites keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.ide.diagnostics import DiagnosticsCollector

__all__ = ["DiagnosticsCollector"]
