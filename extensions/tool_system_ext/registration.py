"""Extension tool registration.

Registers 二开 tools that are not part of upstream's ALL_STATIC_TOOLS.
Called by ``src/tool_system/defaults.py:build_default_registry``.
"""

from __future__ import annotations

from src.tool_system.build_tool import Tool

from clawcodex_ext.tool_system.tools.progress_report import ProgressReportTool
from clawcodex_ext.tool_system.tools.task_directives import TaskDirectivesTool
from clawcodex_ext.tool_system.tools.task_inspect import TaskInspectTool
from clawcodex_ext.goal.tool import GoalTool
from clawcodex_ext.tool_system.tools.create_agent_tool import make_create_agent_tool

EXTENSION_TOOLS: list[Tool] = [
    ProgressReportTool,
    TaskDirectivesTool,
    TaskInspectTool,
    make_create_agent_tool(),
    GoalTool,
]

# F-62 Chrome browser automation — seven ``chrome_*`` tools
# registered when the optional chrome service module is importable.
# The chrome controller depends on Playwright / Pillow / the MCP
# SDK as optional dependencies; the tools themselves are built
# unconditionally and degrade gracefully to a ``NullChromeController``
# that surfaces an install-hint error on every call.
try:
    from src.services.chrome import build_chrome_tools

    EXTENSION_TOOLS.extend(build_chrome_tools())
except Exception:  # noqa: BLE001 — defensive, never break tool registration
    # If the chrome module can't be imported (e.g. mid-refactor
    # or a partial install), the rest of the extension tools
    # still register. The chrome public API is loaded lazily by
    # ``build_chrome_controller`` at first use.
    pass

__all__ = [
    "EXTENSION_TOOLS",
]
