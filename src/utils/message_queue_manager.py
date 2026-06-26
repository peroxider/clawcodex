"""Compatibility facade — see :mod:`clawcodex_ext.utils.message_queue_manager`."""
from __future__ import annotations
import sys
from clawcodex_ext.utils import message_queue_manager as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
