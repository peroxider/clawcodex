"""Facade — command_system/aggregator.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    'get_commands',
    'get_skill_tool_commands',
    'get_slash_command_tool_skills',
    'clear_commands_cache',
]


def __getattr__(name: str):
    import clawcodex_ext.command_system.aggregator as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
