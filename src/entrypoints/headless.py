"""Module-identity facade for the canonical headless entrypoint."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.entrypoints.headless")
sys.modules[__name__] = _ext_mod
