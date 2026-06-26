"""Compatibility facade — see :mod:`clawcodex_ext.services.tool_execution.tool_result_persistence`."""

from __future__ import annotations

import sys

from clawcodex_ext.services.tool_execution import tool_result_persistence as _module

sys.modules[__name__] = _module

__all__ = getattr(_module, '__all__', [])
