"""Compatibility facade — see :mod:`clawcodex_ext.utils.file_state_cache`."""

from __future__ import annotations
import sys
from clawcodex_ext.utils import file_state_cache as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
