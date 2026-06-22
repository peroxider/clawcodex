"""Facade — context_system/microcompact.py moved to clawcodex_ext/context_system/.

The microcompact machinery (``compact_microcompact``, etc.) now lives
in :mod:`clawcodex_ext.context_system.microcompact`. This module
re-exports it verbatim so existing ``from src.context_system.microcompact
import ...`` callers keep working.
"""

from clawcodex_ext.context_system.microcompact import *  # noqa: F401,F403
