"""Facade — src/services/ide/connection.py has been moved to clawcodex_ext.

The full implementation now lives in :mod:`clawcodex_ext.services.ide.connection`.
This module re-exports the public surface so existing
``from src.services.ide.connection import ...`` call sites keep working
without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.ide.connection import (
    IDEConnectionManager,
    PendingRequest,
)

__all__ = ["IDEConnectionManager", "PendingRequest"]
