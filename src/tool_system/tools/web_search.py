"""Facade — tool_system/tools/web_search.py moved to clawcodex_ext/tool_system/tools/."""

from clawcodex_ext.tool_system.tools.web_search import *  # noqa: F401,F403

import sys

from clawcodex_ext.tool_system.tools import web_search as _implementation

sys.modules[__name__] = _implementation
