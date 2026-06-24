"""Facade — services/pricing.py has been moved to clawcodex_ext.

The per-model pricing tables and pure functions now live in
:mod:`clawcodex_ext.services.pricing`. This module re-exports the
public surface so existing ``from src.services.pricing import ...``
callers keep working.
"""

from clawcodex_ext.services.pricing import *  # noqa: F401,F403
