"""Fast-path downstream CLI subcommand registry."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable

SubcommandHandler = Callable[[list[str]], int]

_SUBCOMMANDS: dict[str, SubcommandHandler] = {}
_LOADED = False


def register(name: str) -> Callable[[SubcommandHandler], SubcommandHandler]:
    """Register a fast-path subcommand handler."""

    def decorator(handler: SubcommandHandler) -> SubcommandHandler:
        _SUBCOMMANDS[name] = handler
        return handler

    return decorator


def get_subcommand(name: str) -> SubcommandHandler | None:
    load_builtin_subcommands()
    return _SUBCOMMANDS.get(name)


def load_builtin_subcommands() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    from clawcodex_ext.cli.provider_cmd import commands as _provider_commands  # noqa: F401
    from clawcodex_ext.cli.model_cmd import commands as _model_commands  # noqa: F401
    from clawcodex_ext.cli.pos_cmd import commands as _pos_commands  # noqa: F401
    from clawcodex_ext.cli import telemetry_cmd as _telemetry_cmd  # noqa: F401

    # F-88: ``clawcodex auth logout|status|zeroize``
    from clawcodex_ext.cli import auth_cmd as _auth_cmd  # noqa: F401

    # F-85 P85-D: `clawcodex template list|show|create` subcommand.
    # Some downstream checkouts do not ship the CLI wrapper yet even though
    # the template service modules are present. Treat it as optional so a
    # missing template command cannot break unrelated entry points such as
    # `clawcodex-dev viz`.
    try:
        from clawcodex_ext.cli import template_cmd as _template_cmd  # noqa: F401
    except ImportError:
        _template_cmd = None

    # F-49 P5-H: ``clawcodex-dev session migrate`` subcommand for
    # converting legacy 3-file sessions to the unified 2-file format.
    from clawcodex_ext.cli import session_migrate_cmd as _session_migrate_cmd  # noqa: F401

    # F-94-A: ``clawcodex viz`` subcommand for the Multi-Session Visualizer
    from extensions.visualizer.cli import register_viz_subcommand  # noqa: F401

    register_viz_subcommand()

    # F-75: ``clawcodex stats`` subcommand for tool/skill usage statistics
    from clawcodex_ext.cli import stats_cmd as _stats_cmd  # noqa: F401

    # F-68: ``clawcodex feature`` subcommand for runtime feature-gate management
    from clawcodex_ext.feature_gate.cli import run_feature_command  # noqa: F401

    from extensions.remote_api.cli import register_api_subcommand

    register_api_subcommand()
