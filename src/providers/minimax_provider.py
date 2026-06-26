"""Facade — providers/minimax_provider.py — sys.modules swap.

The real implementation now lives in
``clawcodex_ext.providers.minimax_provider`` (containing both
``MinimaxProvider`` and ``ClawcodexMinimaxProvider``).  This module is
kept as a ``sys.modules`` swap so:

* ``from src.providers.minimax_provider import MinimaxProvider`` (used
  by ``tests/abort/test_minimax_abort_signal.py`` and the lazy
  provider registration hook in ``src/providers/__init__.py``) resolves
  to the real class.
* The lazy provider registration
  (``src.providers.get_provider_class`` returns ``MinimaxProvider``)
  still resolves to the real class.

``sys.modules`` swap is used (rather than ``globals().update``) so the
``clawcodex_ext.providers.minimax_provider.MinimaxProvider`` class
identity is identical to ``src.providers.minimax_provider.
MinimaxProvider`` — this is important for any future
``isinstance``/identity checks and keeps the two paths structurally
equivalent.
"""

from __future__ import annotations

import importlib
import sys

_ext_mod = importlib.import_module('clawcodex_ext.providers.minimax_provider')
sys.modules[__name__] = _ext_mod
