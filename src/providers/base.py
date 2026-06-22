"""Facade — providers/base.py moved to clawcodex_ext/providers/.

The base provider types (``BaseProvider``, ``ChatResponse``,
``ChatMessage``, ``MessageInput``, ``TextChunkCallback``) now live in
:mod:`clawcodex_ext.providers.base`. This module re-exports them
verbatim so existing ``from src.providers.base import ...`` callers
keep working.
"""

from clawcodex_ext.providers.base import *  # noqa: F401,F403
