"""Compatibility facade — see :mod:`clawcodex_ext.bridge.worktree`."""

from __future__ import annotations
import sys
from clawcodex_ext.bridge import worktree as _module

sys.modules[__name__] = _module
__all__ = getattr(_module, '__all__', [])
