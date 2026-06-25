"""Facade — tool_system/tools/write.py moved to clawcodex_ext.tool_system.tools.write (sys.modules swap).

Some tests introspect private internals (functions whose names start
with ``_``) and rely on ``from src.tool_system.tools.write import _something``
resolving against the real module object. The plain
``from clawcodex_ext.tool_system.tools.write import *`` form would silently drop those
underscore-prefixed names. A ``sys.modules`` swap preserves the
underlying ext module as the canonical object so attribute access,
``inspect.getsource()``, and AST walking keep working unchanged.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.tool_system.tools.write')
sys.modules[__name__] = _ext_mod
