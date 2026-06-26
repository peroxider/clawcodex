"""Compatibility facade — see :mod:`clawcodex_ext.bridge.flush_gate`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import flush_gate as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
