"""Facade — command_system/output_style_command.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    'OUTPUT_STYLE_COMMAND',
    'OutputStyleCommand',
]


def __getattr__(name: str):
    import clawcodex_ext.command_system.output_style_command as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
