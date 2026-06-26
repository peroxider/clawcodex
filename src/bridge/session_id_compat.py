"""Compatibility facade — see :mod:`clawcodex_ext.bridge.session_id_compat`."""
from __future__ import annotations
import sys
from clawcodex_ext.bridge import session_id_compat as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
