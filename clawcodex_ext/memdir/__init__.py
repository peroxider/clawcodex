"""Canonical public surface for :mod:`clawcodex_ext.memdir`."""

from __future__ import annotations

import importlib
from typing import Any

from clawcodex_ext.memdir.find_relevant_memories import (
    find_relevant_memories as find_relevant_memories,
)
from clawcodex_ext.memdir.memory_age import memory_age as memory_age

_SYMBOLS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "clawcodex_ext.memdir.find_relevant_memories": (
        "MAX_RELEVANT_MEMORIES",
        "RelevantMemory",
        "find_relevant_memories",
    ),
    "clawcodex_ext.memdir.memdir": (
        "DIR_EXISTS_GUIDANCE",
        "ENTRYPOINT_NAME",
        "EntrypointTruncation",
        "MAX_ENTRYPOINT_BYTES",
        "MAX_ENTRYPOINT_LINES",
        "build_memory_lines",
        "build_memory_prompt",
        "ensure_memory_dir_exists",
        "load_memory_prompt",
        "truncate_entrypoint_content",
    ),
    "clawcodex_ext.memdir.memory_age": (
        "memory_age",
        "memory_age_days",
        "memory_freshness_note",
        "memory_freshness_text",
    ),
    "clawcodex_ext.memdir.memory_scan": (
        "FRONTMATTER_MAX_LINES",
        "MAX_DEPTH",
        "MAX_MEMORY_FILES",
        "MemoryHeader",
        "format_memory_manifest",
        "scan_memory_files",
    ),
    "clawcodex_ext.memdir.memory_types": (
        "MEMORY_DRIFT_CAVEAT",
        "MEMORY_FRONTMATTER_EXAMPLE",
        "MEMORY_TYPES",
        "MemoryType",
        "TRUSTING_RECALL_SECTION",
        "TYPES_SECTION_INDIVIDUAL",
        "WHAT_NOT_TO_SAVE_SECTION",
        "WHEN_TO_ACCESS_SECTION",
        "parse_memory_type",
    ),
    "clawcodex_ext.memdir.paths": (
        "find_canonical_git_root",
        "get_auto_mem_daily_log_path",
        "get_auto_mem_entrypoint",
        "get_auto_mem_path",
        "get_memory_base_dir",
        "has_auto_mem_path_override",
        "is_auto_mem_path",
        "is_auto_memory_enabled",
        "sanitize_path",
    ),
    "clawcodex_ext.memdir.team_mem_paths": (
        "PathTraversalError",
        "get_team_mem_entrypoint",
        "get_team_mem_path",
        "is_team_mem_file",
        "is_team_mem_path",
        "is_team_memory_enabled",
        "validate_team_mem_key",
        "validate_team_mem_write_path",
    ),
    "clawcodex_ext.memdir.team_mem_prompts": (
        "DIRS_EXIST_GUIDANCE",
        "TYPES_SECTION_COMBINED",
        "build_combined_memory_prompt",
    ),
}
_SYMBOL_MODULES = {
    symbol: module_name for module_name, symbols in _SYMBOLS_BY_MODULE.items() for symbol in symbols
}

__all__ = list(_SYMBOL_MODULES)


def __getattr__(name: str) -> Any:
    try:
        module_name = _SYMBOL_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
