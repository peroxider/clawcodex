"""Module-identity facade for canonical session hooks."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.hooks.session_hooks")
sys.modules[__name__] = _ext_mod
