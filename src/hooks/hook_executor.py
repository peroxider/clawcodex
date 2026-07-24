"""Module-identity facade for the canonical hook executor."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.hooks.hook_executor")
sys.modules[__name__] = _ext_mod
