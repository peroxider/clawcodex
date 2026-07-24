"""Compatibility facade — see :mod:`clawcodex_ext.services.tool_execution.tool_execution`."""

from clawcodex_ext.services.tool_execution.tool_execution import *  # noqa: F401,F403

import sys

from clawcodex_ext.services.tool_execution import tool_execution as _implementation

sys.modules[__name__] = _implementation
