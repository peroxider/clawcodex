"""Compatibility shim — delegate to lkb.adapters with LkbToolResult → ToolResult conversion."""

from typing import Any

from lkb.adapters import (  # noqa: F401
    _accepted_lkb,
    _denied_result as _lkb_denied_result,
    maybe_commit_task_update,
    maybe_commit_todo_write,
    prepare_task_change,
    prepare_todo_write,
)
from lkb.types import LkbToolResult
from clawcodex_ext.tool_system.protocol import ToolResult


def _denied_result(
    tool_name: str,
    proposal: Any,
    validation: Any,
    commit: Any,
) -> ToolResult:
    """Convert LkbToolResult → clawcodex ToolResult at boundary."""
    lkb_result = _lkb_denied_result(tool_name, proposal, validation, commit)
    return ToolResult(
        name=lkb_result.name,
        output=lkb_result.output,
        is_error=lkb_result.is_error,
    )