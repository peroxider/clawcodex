"""Facade — permissions/modes.py has been moved to clawcodex_ext (lazy proxy).

Uses module-level ``__getattr__`` to defer the ext import until the
symbol is actually accessed at runtime. This avoids facade re-entrancy
when a sibling module's top-level imports chain through this file
during ``clawcodex_ext/__init__.py`` initialization.
"""

from __future__ import annotations

import importlib

_ext_mod = None


def __getattr__(name: str):
    global _ext_mod
    if _ext_mod is None:
        _ext_mod = importlib.import_module("clawcodex_ext.permissions.modes")
    return getattr(_ext_mod, name)
