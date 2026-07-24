"""Module-identity facade for bundled-skill registry compatibility."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.skills.bundled_skills")
sys.modules[__name__] = _ext_mod
