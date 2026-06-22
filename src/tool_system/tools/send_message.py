"""Facade — tool_system/tools/send_message.py moved to clawcodex_ext/.

Replaces itself in ``sys.modules`` with the underlying ext module so
introspection (``inspect.getsource``, ``inspect.getfile``, AST walks)
operates on the real implementation rather than this thin shim.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.tool_system.tools.send_message")
sys.modules[__name__] = _ext_mod
