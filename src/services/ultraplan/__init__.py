"""Facade — services/ultraplan/ moved to clawcodex_ext/services/ultraplan/.

The full F-83 implementation now lives in
:mod:`clawcodex_ext.services.ultraplan`. This module re-exports it
verbatim so existing ``from src.services.ultraplan import ...`` callers
keep working without modification.
"""

from clawcodex_ext.services.ultraplan import *  # noqa: F401,F403
