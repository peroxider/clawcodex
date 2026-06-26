"""Compatibility facade — see :mod:`clawcodex_ext.bridge.env_less_bridge_config`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import env_less_bridge_config as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
