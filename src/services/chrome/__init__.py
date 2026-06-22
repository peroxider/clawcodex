"""Compatibility facade — see :mod:`clawcodex_ext.services.chrome`.

The real implementation lives in ``clawcodex_ext/services/chrome``.
This package re-exports the public surface so legacy
``from src.services.chrome import ...`` callers keep working.
"""

from __future__ import annotations

from clawcodex_ext.services.chrome import *  # noqa: F401,F403
from clawcodex_ext.services.chrome import (  # noqa: F401 — re-export
    ChromeActionResult,
    ChromeActionType,
    ChromeController,
    ChromeError,
    MCPChromeController,
    NullChromeController,
    PlaywrightChromeController,
    RecordingChromeController,
    _reset_chrome_singleton,
    build_chrome_controller,
    build_chrome_tools,
)

__all__ = [
    "ChromeActionResult",
    "ChromeActionType",
    "ChromeController",
    "ChromeError",
    "MCPChromeController",
    "NullChromeController",
    "PlaywrightChromeController",
    "RecordingChromeController",
    "_reset_chrome_singleton",
    "build_chrome_controller",
    "build_chrome_tools",
]
