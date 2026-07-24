"""Compatibility facade — see :mod:`clawcodex_ext.state`.

Module-identity swap. ``src.state.__init__`` is consumed by tooling that
inspects the package's archive metadata (e.g. ``from src.state import
ARCHIVE_NAME``); the canonical implementation is registered under the
legacy import path so those reads resolve to the same module object.
"""

from __future__ import annotations

import sys

import clawcodex_ext.state as _ext_pkg
import clawcodex_ext.state.cache_state as _cache_state

_ext_pkg.cache_state = _cache_state
sys.modules[f"{__name__}.cache_state"] = _cache_state
sys.modules[__name__] = _ext_pkg

__all__ = getattr(_ext_pkg, '__all__', [])
