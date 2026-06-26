"""Compatibility facade — see :mod:`clawcodex_ext.transports.sse_transport`."""
from __future__ import annotations
import sys
from clawcodex_ext.transports import sse_transport as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
