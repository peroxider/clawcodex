"""Facade — tool_system/protocol.py moved to clawcodex_ext/tool_system/.

The tool protocol types (``ToolCall``, ``ToolResult``) now live in
:mod:`clawcodex_ext.tool_system.protocol`. This module re-exports them
verbatim so existing ``from src.tool_system.protocol import ...``
callers keep working.
"""

from clawcodex_ext.tool_system.protocol import *  # noqa: F401,F403
