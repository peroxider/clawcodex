"""Facade — services/templates/ moved to clawcodex_ext/services/templates/.

The full F-85 implementation now lives in
:mod:`clawcodex_ext.services.templates`. This module re-exports it
verbatim so existing ``from src.services.templates import ...`` callers
keep working without modification.
"""

from clawcodex_ext.services.templates import *  # noqa: F401,F403
