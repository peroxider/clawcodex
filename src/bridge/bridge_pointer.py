"""Compatibility facade — see :mod:`clawcodex_ext.bridge.bridge_pointer`."""

from __future__ import annotations
import sys
from clawcodex_ext.bridge import bridge_pointer as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
