"""Module-identity bridge to the downstream stop-hook implementation."""

from __future__ import annotations

import importlib
import sys

_ext_module = importlib.import_module("clawcodex_ext.query.stop_hooks")
sys.modules[__name__] = _ext_module
