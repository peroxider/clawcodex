"""Facade — compact_service/messages.py moved to clawcodex_ext/compact_service/.

The compact-service message helpers (``is_compact_boundary_message``,
``create_compact_boundary_message``, etc.) now live in
:mod:`clawcodex_ext.compact_service.messages`. This module re-exports
them verbatim so existing ``from src.compact_service.messages import
...`` callers keep working.
"""

from clawcodex_ext.compact_service.messages import *  # noqa: F401,F403
