"""Facade — tool_system/tools/skill.py moved to clawcodex_ext/tool_system/tools/."""

from clawcodex_ext.tool_system.tools.skill import *  # noqa: F401,F403

import sys

from clawcodex_ext.tool_system.tools import skill as _implementation

sys.modules[__name__] = _implementation
