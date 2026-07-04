"""Compatibility facade — see :mod:`clawcodex_ext.bridge.inbound_messages`."""

from __future__ import annotations
import sys
from clawcodex_ext.bridge import inbound_messages as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
