"""Compatibility facade — see :mod:`clawcodex_ext.bridge.no_proxy`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import no_proxy as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
