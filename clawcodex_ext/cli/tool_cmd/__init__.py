"""Tool 自动暴露为 CLI 斜杠命令.

Public API
----------
* :class:`DynamicCommandDiscovery` — scan a ``ToolRegistry`` for non-core
  tools and produce ``LocalCommand``s.
* :class:`DynamicToolCommand` — single-tool adapter; bind to REPL/TUI
  ``CommandContext`` for invocation.
* :func:`install_tool_subcommand` — register the ``clawcodex-dev tool``
  CLI subcommand (idempotent).
* :func:`register_tool_commands` — register per-tool slash commands in
  a REPL/TUI ``CommandRegistry``.

Usage
-----
At REPL/TUI startup (after the runtime context is built)::

    from clawcodex_ext.cli.tool_cmd import register_tool_commands
    from clawcodex_ext.command_system.registry import CommandRegistry

    command_registry = CommandRegistry()
    register_tool_commands(command_registry, ctx.tool_registry)

From the CLI::

    clawcodex-dev tool --list
    clawcodex-dev tool detect_modality --path /data/sample.mp4
"""

from __future__ import annotations

from .command import DynamicToolCommand
from .discovery import DynamicCommandDiscovery
from .hooks import install_tool_subcommand, register_tool_commands
from . import core_filter, schema_parser

__all__ = [
    "DynamicCommandDiscovery",
    "DynamicToolCommand",
    "core_filter",
    "install_tool_subcommand",
    "register_tool_commands",
    "schema_parser",
]
