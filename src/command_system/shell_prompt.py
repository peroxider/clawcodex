"""Facade — command_system/shell_prompt.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    'ShellExecutor',
    'execute_shell_commands_in_prompt',
    'make_bash_shell_executor',
]


def __getattr__(name: str):
    import clawcodex_ext.command_system.shell_prompt as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
