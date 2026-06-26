"""Compatibility facade — see :mod:`clawcodex_ext.transports.ccr_client`."""
from __future__ import annotations
import sys
from clawcodex_ext.transports import ccr_client as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
