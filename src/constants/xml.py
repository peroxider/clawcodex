"""Facade — constants/xml.py moved to clawcodex_ext/constants/.

The XML tag constants now live in :mod:`clawcodex_ext.constants.xml`.
This module re-exports them verbatim so existing
``from src.constants.xml import ...`` callers keep working.
"""

from clawcodex_ext.constants.xml import *  # noqa: F401,F403