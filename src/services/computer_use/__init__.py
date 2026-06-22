"""Facade — src/services/computer_use/__init__.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.computer_use`. This module re-exports the public surface so
existing ``from src.services.computer_use. import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.computer_use import *  # noqa: F401,F403
