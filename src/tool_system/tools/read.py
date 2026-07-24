"""Facade — tool_system/tools/read.py moved to clawcodex_ext/tool_system/tools/."""

from clawcodex_ext.tool_system.tools.read import *  # noqa: F401,F403

import sys

from clawcodex_ext.tool_system.tools import read as _implementation

sys.modules[__name__] = _implementation
