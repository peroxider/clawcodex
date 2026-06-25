"""Compatibility facade — see :mod:`clawcodex_ext.utils.combined_abort_signal`."""

from __future__ import annotations
import sys
from clawcodex_ext.utils import combined_abort_signal as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
