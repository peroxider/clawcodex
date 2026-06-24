"""Facade — computer_use/platform/__init__ has been moved to clawcodex_ext.

The real implementation now lives in
:mod:`clawcodex_ext.services.computer_use.platform`. This module swaps
itself out at import time (Pattern C) so that ``_current_platform`` and
other private symbols remain accessible to tests.
"""

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.services.computer_use.platform")
sys.modules[__name__] = _ext_mod
