"""Compatibility facade — see :mod:`clawcodex_ext.transports.worker_state_uploader`."""
from __future__ import annotations
import sys
from clawcodex_ext.transports import worker_state_uploader as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
