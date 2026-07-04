"""Facade — tool_system/utils/ripgrep.py moved to clawcodex_ext/tool_system/utils/ (sys.modules swap)."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.tool_system.utils.ripgrep')
sys.modules[__name__] = _ext_mod
