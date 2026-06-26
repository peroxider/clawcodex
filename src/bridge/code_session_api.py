"""Compatibility facade — see :mod:`clawcodex_ext.bridge.code_session_api`."""

from __future__ import annotations

import sys

from clawcodex_ext.bridge import code_session_api as _module

sys.modules[__name__] = _module

__all__ = getattr(_module, '__all__', [])
