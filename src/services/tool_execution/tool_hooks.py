"""Facade — src/services/tool_execution/tool_hooks.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.tool_execution.tool_hooks`. This module
re-exports the public surface so existing
``from src.services.tool_execution.tool_hooks import ...`` call sites
keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.tool_execution.tool_hooks import (
    PreToolUseResult,
    resolve_hook_permission_decision,
    run_post_tool_use_failure_hooks,
    run_post_tool_use_hooks,
    run_pre_tool_use_hooks,
)

__all__ = [
    "PreToolUseResult",
    "resolve_hook_permission_decision",
    "run_post_tool_use_failure_hooks",
    "run_post_tool_use_hooks",
    "run_pre_tool_use_hooks",
]
