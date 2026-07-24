"""Facade — tool_system/tools/web_fetch.py moved to clawcodex_ext/tool_system/tools/."""

from clawcodex_ext.tool_system.tools.web_fetch import *  # noqa: F401,F403

import sys

from clawcodex_ext.tool_system.tools import web_fetch as _implementation

sys.modules[__name__] = _implementation
