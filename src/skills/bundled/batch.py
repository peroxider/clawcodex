"""Module-identity facade for the canonical bundled Batch skill."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.skills.bundled.batch")
sys.modules[__name__] = _ext_mod
