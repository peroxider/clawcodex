"""Facade — command_system/safe_commands.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    "REMOTE_SAFE_COMMANDS",
    "BRIDGE_SAFE_COMMANDS",
    "is_bridge_safe_command",
    "filter_commands_for_remote_mode",
]


def __getattr__(name: str):
    import clawcodex_ext.command_system.safe_commands as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
