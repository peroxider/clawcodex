"""Facade — src/services/ide/selection.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.ide.selection`. This module re-exports the
public surface so existing ``from src.services.ide.selection import ...``
call sites keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.ide.selection import SelectionEntry, SelectionTracker

__all__ = ["SelectionEntry", "SelectionTracker"]
