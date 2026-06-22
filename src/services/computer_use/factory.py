"""Facade — src/services/computer_use/factory.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.computer_use.factory`. This module re-exports the public surface so
existing ``from src.services.computer_use.factory import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.computer_use.factory import (  # noqa: F401
    build_computer_use_suite,
)

__all__ = ['build_computer_use_suite']
