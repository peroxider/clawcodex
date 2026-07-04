"""Compatibility facade — see :mod:`clawcodex_ext.remote.sessions_websocket`."""

from __future__ import annotations

import sys

from clawcodex_ext.remote import sessions_websocket as _module

sys.modules[__name__] = _module

__all__ = getattr(_module, '__all__', [])
