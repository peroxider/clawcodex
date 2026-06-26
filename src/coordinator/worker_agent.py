"""Compatibility facade — see :mod:`clawcodex_ext.coordinator.worker_agent`."""
from __future__ import annotations
import sys
from clawcodex_ext.coordinator import worker_agent as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
