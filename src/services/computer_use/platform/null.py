"""Facade — computer_use/platform/null.py has been moved to clawcodex_ext.

The real implementation now lives in
:mod:`clawcodex_ext.services.computer_use.platform.null`. This module
re-exports the public surface so existing ``from src.services.computer_use
.platform.null import ...`` callers keep working.
"""

from clawcodex_ext.services.computer_use.platform.null import *  # noqa: F401,F403
