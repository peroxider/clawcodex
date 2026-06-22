"""Facade — src/services/computer_use/dry_run.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.computer_use.dry_run`. This module re-exports the public surface so
existing ``from src.services.computer_use.dry_run import ...``
call sites keep working without modification.
"""

from clawcodex_ext.services.computer_use.dry_run import (  # noqa: F401
    DryRunRecorder,
    region_to_args,
    window_to_args,
)

__all__ = ['DryRunRecorder', 'region_to_args', 'window_to_args']
