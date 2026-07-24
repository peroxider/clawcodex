"""Module-identity facade for compact-service message helpers."""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.compact_service.messages")
sys.modules[__name__] = _ext_mod
