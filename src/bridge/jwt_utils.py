"""Compatibility facade — see :mod:`clawcodex_ext.bridge.jwt_utils`."""

from __future__ import annotations
import sys
from clawcodex_ext.bridge import jwt_utils as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
