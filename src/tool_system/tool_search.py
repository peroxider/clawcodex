"""Facade — tool_system/tool_search.py moved to clawcodex_ext.tool_system.tool_search (sys.modules swap).

Some tests introspect private internals (functions whose names start
with ``_``) and rely on ``from src.tool_system.tool_search import _something``
resolving against the real module object. The plain
``from clawcodex_ext.tool_system.tool_search import *`` form would silently drop those
underscore-prefixed names. A ``sys.modules`` swap preserves the
underlying ext module as the canonical object so attribute access,
``inspect.getsource()``, and AST walking keep working unchanged.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.tool_system.tool_search')
sys.modules[__name__] = _ext_mod
