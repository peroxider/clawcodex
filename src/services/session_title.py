"""Facade — services/session_title.py has been moved to clawcodex_ext.

The session title generation functions now live in
:mod:`clawcodex_ext.services.session_title`. This module re-exports
the public surface so existing ``from src.services.session_title
import ...`` callers keep working.
"""

from clawcodex_ext.services.session_title import *  # noqa: F401,F403
