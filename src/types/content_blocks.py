"""Facade — types/content_blocks.py moved to clawcodex_ext/types/.

The full typed content block dataclasses now live in
:mod:`clawcodex_ext.types.content_blocks`. This module re-exports
them verbatim so existing ``from src.types.content_blocks import ...``
callers keep working.
"""

from clawcodex_ext.types.content_blocks import *  # noqa: F401,F403
