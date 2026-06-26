"""Compatibility facade — see :mod:`clawcodex_ext.bridge.repl_bridge_handle`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import repl_bridge_handle as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
