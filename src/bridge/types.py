"""Compatibility facade — see :mod:`clawcodex_ext.bridge.types`."""

from __future__ import annotations

import sys

from clawcodex_ext.bridge import types as _module

sys.modules[__name__] = _module

__all__ = getattr(_module, '__all__', [])
