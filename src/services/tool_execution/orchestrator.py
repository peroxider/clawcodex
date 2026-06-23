"""Facade — src/services/tool_execution/orchestrator.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.tool_execution.orchestrator`. This module
re-exports the public surface so existing
``from src.services.tool_execution.orchestrator import ...`` call sites
keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.tool_execution.orchestrator import (
    Batch,
    ToolUseBlock,
    classify_concurrency_safe,
    partition_tool_calls,
    run_tools,
)

__all__ = [
    "Batch",
    "ToolUseBlock",
    "classify_concurrency_safe",
    "partition_tool_calls",
    "run_tools",
]
