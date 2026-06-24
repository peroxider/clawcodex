"""Downstream ClawCodex bridge implementations.

Phase 4 P1 (Option A) migrated 9 bridge modules here from
``src/bridge/``. The canonical re-export surface lives in
``src/bridge/__init__.py`` — each per-module ``src/bridge/X.py`` is a
thin ``sys.modules`` swap facade that forwards to the corresponding
``clawcodex_ext.bridge.X`` here. This __init__ stays minimal on purpose:
any re-export of ``src.bridge.*`` symbols from here would create a
circular import (src.bridge.X facade → clawcodex_ext.bridge.X →
clawcodex_ext.bridge.__init__ → src.bridge.X facade → ...).
"""
from __future__ import annotations