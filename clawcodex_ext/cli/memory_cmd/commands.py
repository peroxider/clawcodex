"""Manage the bundled ClawCodex long-term memory service."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clawcodex_ext.cli.subcommand_registry import register


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Memory state directory (default: CLAWCODEX_MEMORY_STATE_DIR or ~/.clawcodex/memory).",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional memory environment file; process environment remains highest priority.",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clawcodex-dev memory",
        description="Manage the bundled Mem0-compatible memory service.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enable_parser = subparsers.add_parser(
        "enable", help="Enable project memory and start its server in background."
    )
    _add_common_paths(enable_parser)
    enable_parser.add_argument("--timeout", type=float, default=60.0)

    disable_parser = subparsers.add_parser(
        "disable", help="Stop the memory server and disable project memory."
    )
    _add_common_paths(disable_parser)
    disable_parser.add_argument("--timeout", type=float, default=10.0)

    restart_parser = subparsers.add_parser("restart", help="Restart the memory server.")
    _add_common_paths(restart_parser)
    restart_parser.add_argument("--timeout", type=float, default=60.0)

    status_parser = subparsers.add_parser("status", help="Show memory server health.")
    _add_common_paths(status_parser)

    logs_parser = subparsers.add_parser("logs", help="Read the memory server log.")
    _add_common_paths(logs_parser)
    logs_parser.add_argument("-f", "--follow", action="store_true")
    logs_parser.add_argument("--lines", type=int, default=200)

    serve_parser = subparsers.add_parser("serve", help="Run the memory server in foreground.")
    _add_common_paths(serve_parser)
    subparsers.add_parser("mcp", help="Run the stdio MCP bridge.")
    return parser


@register("memory")
def run_memory_command(args: list[str]) -> int:
    if args and args[0] == "mcp":
        from clawcodex_ext.latent_memory.server.mcp_server import main as mcp_main

        return mcp_main(args[1:])

    parser = _build_parser()
    parsed = parser.parse_args(args)

    from clawcodex_ext.latent_memory.server.daemon import (
        MemoryServerDaemon,
        MemoryServerPaths,
        load_memory_environment,
        serve_foreground,
    )

    try:
        load_memory_environment(parsed.env_file, state_dir=parsed.state_dir)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    paths = MemoryServerPaths.for_state_dir(parsed.state_dir)
    daemon = MemoryServerDaemon(paths)
    if parsed.command in {"enable", "restart", "serve"}:
        from clawcodex_ext.latent_memory.project_integration import enable_project_integration

        try:
            mcp_path, env_path = enable_project_integration()
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"Memory integration enabled: {mcp_path}")
        print(f"Passive memory enabled: {env_path}")
    if parsed.command == "enable":
        return daemon.start(env_file=parsed.env_file, timeout=parsed.timeout)
    if parsed.command == "disable":
        stop_result = daemon.stop(timeout=parsed.timeout)
        from clawcodex_ext.latent_memory.project_integration import disable_project_integration

        try:
            mcp_path, env_path = disable_project_integration()
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return stop_result or 2
        print(f"Memory integration disabled: {mcp_path}")
        print(f"Passive memory disabled: {env_path}")
        return stop_result
    if parsed.command == "restart":
        return daemon.restart(env_file=parsed.env_file, timeout=parsed.timeout)
    if parsed.command == "status":
        return daemon.status()
    if parsed.command == "logs":
        return daemon.logs(lines=parsed.lines, follow=parsed.follow)
    if parsed.command == "serve":
        try:
            return serve_foreground(Path(paths.state_dir))
        finally:
            from clawcodex_ext.latent_memory.project_integration import (
                disable_project_integration,
                set_passive_memory_enabled,
            )

            try:
                mcp_path, env_path = disable_project_integration()
            except (OSError, ValueError) as exc:
                try:
                    env_path = set_passive_memory_enabled(False)
                except (OSError, ValueError) as passive_exc:
                    print(
                        "warning: memory server stopped, but project memory cleanup "
                        f"failed: {exc}; passive-memory cleanup also failed: {passive_exc}",
                        file=sys.stderr,
                    )
                else:
                    print(f"Passive memory disabled: {env_path}")
                    print(
                        "warning: memory server stopped and passive memory was disabled, "
                        f"but the MCP configuration could not be removed: {exc}",
                        file=sys.stderr,
                    )
            else:
                print(f"Memory integration disabled: {mcp_path}")
                print(f"Passive memory disabled: {env_path}")
    return 2


__all__ = ["run_memory_command"]
