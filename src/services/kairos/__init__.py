"""Facade — src/services/kairos/__init__.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.kairos`. This module re-exports the public surface so
existing ``from src.services.kairos. import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.kairos import *  # noqa: F401,F403
