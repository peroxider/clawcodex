"""Compatibility facade — see :mod:`clawcodex_ext.services.tool_execution.orchestrator`."""

from clawcodex_ext.services.tool_execution.orchestrator import *  # noqa: F401,F403

import sys

from clawcodex_ext.services.tool_execution import orchestrator as _implementation

sys.modules[__name__] = _implementation
