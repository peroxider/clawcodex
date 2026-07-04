"""Compatibility facade — see :mod:`clawcodex_ext.state.session_start`.

Module-identity swap. The canonical implementation is registered
under the legacy import path so callers using
``from src.state.session_start import ...`` resolve to the same module
object.
"""

from __future__ import annotations

import sys

import clawcodex_ext.state.session_start as _ext_mod

sys.modules[__name__] = _ext_mod

__all__ = getattr(_ext_mod, '__all__', [])
