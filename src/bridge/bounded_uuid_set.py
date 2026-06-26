"""Compatibility facade — see :mod:`clawcodex_ext.bridge.bounded_uuid_set`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import bounded_uuid_set as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
