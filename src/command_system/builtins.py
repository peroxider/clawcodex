"""Facade — command_system/builtins.py has been moved to clawcodex_ext (lazy proxy)."""

from __future__ import annotations

__all__ = [
    "clear_command_call",
    "help_command_call",
    "skills_command_call",
    "exit_command_call",
    "cron_list_command_call",
    "cron_delete_command_call",
    "cost_command_call",
    "context_command_call",
    "advisor_command_call",
    "compact_command_call",
    "execute_command_sync",
    "get_builtin_commands",
    "register_builtin_commands",
    "execute_command_async",
    "get_command_registry",
]


def get_command_registry():
    from src.command_system.registry import get_command_registry as _get_command_registry

    return _get_command_registry()


def _with_facade_registry(call, *args, **kwargs):
    import clawcodex_ext.command_system.builtins as _mod

    original = _mod.get_command_registry
    _mod.get_command_registry = get_command_registry
    try:
        return call(*args, **kwargs)
    finally:
        _mod.get_command_registry = original


def execute_command_sync(cmd_name, args, context):
    import clawcodex_ext.command_system.builtins as _mod

    return _with_facade_registry(_mod.execute_command_sync, cmd_name, args, context)


async def execute_command_async(cmd_name, args, context):
    import clawcodex_ext.command_system.builtins as _mod

    original = _mod.get_command_registry
    _mod.get_command_registry = get_command_registry
    try:
        return await _mod.execute_command_async(cmd_name, args, context)
    finally:
        _mod.get_command_registry = original


def register_builtin_commands(registry=None) -> None:
    import clawcodex_ext.command_system.builtins as _mod

    return _with_facade_registry(_mod.register_builtin_commands, registry)


def get_builtin_commands():
    import clawcodex_ext.command_system.builtins as _mod

    return _mod.get_builtin_commands()


def __getattr__(name: str):
    import clawcodex_ext.command_system.builtins as _mod

    if name in _mod.__dict__:
        val = _mod.__dict__[name]
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
