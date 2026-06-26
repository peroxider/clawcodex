"""Compatibility facade — see :mod:`clawcodex_ext.assistant.session_chooser`."""
from __future__ import annotations
import sys
from clawcodex_ext.assistant import session_chooser as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
