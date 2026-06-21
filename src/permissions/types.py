"""Facade — permissions/types.py moved to clawcodex_ext/permissions/.

The full permission type hierarchy (``PermissionMode``,
``ToolPermissionContext``, ``PermissionRule``,
``EXTERNAL_PERMISSION_MODES``, decision reason types, etc.) now lives
in :mod:`clawcodex_ext.permissions.types`. This module re-exports it
verbatim so existing ``from src.permissions.types import ...`` callers
keep working.
"""

from clawcodex_ext.permissions.types import *  # noqa: F401,F403
