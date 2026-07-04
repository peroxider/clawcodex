"""Compatibility facade — see :mod:`clawcodex_ext.remote.remote_session_manager`."""

from __future__ import annotations

import sys

from clawcodex_ext.remote import remote_session_manager as _module

sys.modules[__name__] = _module

__all__ = getattr(_module, '__all__', [])
