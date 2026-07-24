"""Compatibility bridge to the upstream CLAWCODEX.md context loader."""

from __future__ import annotations

import sys

from src.context_system import clawcodex_md as _module

sys.modules[__name__] = _module
