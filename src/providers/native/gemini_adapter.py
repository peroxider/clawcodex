"""Facade — providers/native/gemini_adapter.py has been moved to clawcodex_ext/providers/native/gemini_adapter.py.

Uses ``sys.modules`` swap so the import identity remains the same as the
real implementation module — callers (and the package ``__init__``
``__getattr__`` hook) refer to it by name.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.providers.native.gemini_adapter")
sys.modules[__name__] = _ext_mod