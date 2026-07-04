"""Compatibility facade — see :mod:`clawcodex_ext.state.cache_state`.

Module-identity swap. ``src.state.cache_state`` owns the
``_LATCHES`` singleton and the ``reset_for_test_only`` escape hatch
that dozens of tests call directly. The canonical implementation is
registered under the legacy import path so those patches resolve to
the same module object.
"""

from __future__ import annotations

import sys

import clawcodex_ext.state.cache_state as _ext_mod

sys.modules[__name__] = _ext_mod

__all__ = getattr(_ext_mod, '__all__', [])
