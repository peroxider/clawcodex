"""Compatibility facade — see :mod:`clawcodex_ext.utils.env`."""
from __future__ import annotations
import sys
from clawcodex_ext.utils import env as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
