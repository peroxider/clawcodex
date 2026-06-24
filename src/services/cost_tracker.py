"""Facade — services/cost_tracker.py has been moved to clawcodex_ext.

The ``CostTracker`` test-only class now lives in
:mod:`clawcodex_ext.services.cost_tracker`. This module swaps
itself out at import time (Pattern C) so that ``_get_pricing`` and
other private symbols remain accessible to tests.
"""

import importlib
import sys

_ext_mod = importlib.import_module("clawcodex_ext.services.cost_tracker")
sys.modules[__name__] = _ext_mod
