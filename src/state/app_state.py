"""Compatibility facade — see :mod:`clawcodex_ext.state.app_state`.

Module-identity swap. Tests import the submodule by path (e.g.
``from src.state import app_state`` / ``from src.state.app_state import
AppState``); the canonical implementation is registered under the
legacy import path so those references resolve to the same module
object.
"""

from __future__ import annotations

import sys

import clawcodex_ext.state.app_state as _ext_mod

sys.modules[__name__] = _ext_mod

__all__ = getattr(_ext_mod, '__all__', [])
