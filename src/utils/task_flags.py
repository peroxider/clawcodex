"""Compatibility facade — see :mod:`clawcodex_ext.utils.task_flags`."""
from __future__ import annotations
import sys
from clawcodex_ext.utils import task_flags as _module
sys.modules[__name__] = _module
__all__ = getattr(_module, "__all__", [])
