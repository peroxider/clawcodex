"""Facade — src/services/computer_use/models.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.computer_use.models`. This module re-exports the public surface so
existing ``from src.services.computer_use.models import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.computer_use.models import (  # noqa: F401
    MouseButton,
    ScrollDirection,
    ScreenRegion,
    WindowRef,
    InputAction,
)

__all__ = ['MouseButton', 'ScrollDirection', 'ScreenRegion', 'WindowRef', 'InputAction']
