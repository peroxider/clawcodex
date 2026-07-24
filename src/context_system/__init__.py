"""Facade — context_system/ has been moved to clawcodex_ext/context_system/."""

from __future__ import annotations

__all__ = [
    "build_context_prompt",
    "append_system_context",
    "clear_context_caches",
    "fetch_system_prompt_parts",
    "get_system_context",
    "get_user_context",
    "prepend_user_context",
    "clear_memory_file_caches",
    "get_clawcodex_mds",
    "get_memory_files",
    "reset_get_memory_files_cache",
    "GitContextSnapshot",
    "clear_git_caches",
    "collect_git_context",
    "format_git_status",
    "get_is_git",
    "MemoryFileInfo",
    "MemoryType",
    "SystemPromptParts",
]


def __getattr__(name: str):
    """Resolve public context symbols after both packages initialise."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import clawcodex_ext.context_system as _module

    value = getattr(_module, name)
    globals()[name] = value
    return value
