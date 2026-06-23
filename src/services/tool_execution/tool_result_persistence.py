"""Facade — src/services/tool_execution/tool_result_persistence.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.tool_execution.tool_result_persistence`.
This module re-exports the public surface so existing
``from src.services.tool_execution.tool_result_persistence import ...``
call sites keep working without modification.
"""

from __future__ import annotations

from clawcodex_ext.services.tool_execution.tool_result_persistence import (
    DEFAULT_MAX_RESULT_SIZE_CHARS,
    PERSISTED_OUTPUT_CLOSING_TAG,
    PERSISTED_OUTPUT_TAG,
    PREVIEW_SIZE_BYTES,
    PersistResult,
    PersistToolResultError,
    PersistedToolResult,
    build_large_tool_result_message,
    compute_block_chars,
    generate_preview,
    get_persistence_threshold,
    is_persist_error,
    is_tool_result_content_empty,
    maybe_persist_large_tool_result,
    persist_tool_result,
    process_tool_result_block,
    resolve_tool_results_dir,
)

__all__ = [
    "DEFAULT_MAX_RESULT_SIZE_CHARS",
    "PERSISTED_OUTPUT_CLOSING_TAG",
    "PERSISTED_OUTPUT_TAG",
    "PREVIEW_SIZE_BYTES",
    "PersistResult",
    "PersistToolResultError",
    "PersistedToolResult",
    "build_large_tool_result_message",
    "compute_block_chars",
    "generate_preview",
    "get_persistence_threshold",
    "is_persist_error",
    "is_tool_result_content_empty",
    "maybe_persist_large_tool_result",
    "persist_tool_result",
    "process_tool_result_block",
    "resolve_tool_results_dir",
]
