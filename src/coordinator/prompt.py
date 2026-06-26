"""Compatibility facade — see :mod:`clawcodex_ext.coordinator.prompt`."""
from __future__ import annotations
import sys
from clawcodex_ext.coordinator import prompt as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
