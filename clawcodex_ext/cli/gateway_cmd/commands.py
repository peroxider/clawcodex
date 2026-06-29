"""``clawcodex-dev gateway`` subcommand — manage the Gateway daemon.

Usage:
  clawcodex-dev gateway server status          Show daemon status
  clawcodex-dev gateway server start           Start the daemon
  clawcodex-dev gateway server stop            Stop the daemon
  clawcodex-dev gateway server restart         Restart the daemon

All commands are idempotent. v1 runs POSIX UDS only; acceptance is
limited to POSIX/WSL/Git Bash.
"""

from __future__ import annotations

import sys

from clawcodex_ext.cli.subcommand_registry import register

_USAGE = (
    "usage: clawcodex-dev gateway server {start|stop|status|restart} [-v|--verbose]\n\n"
    "Manage the IM Message Gateway daemon.\n"
    "  server status    Show whether the daemon is running.\n"
    "  server start     Start the daemon (idempotent).\n"
    "  server stop      Stop the daemon (idempotent).\n"
    "  server restart   Stop then start.\n"
    "  -v, --verbose    Enable INFO-level IM logging (default: ERROR/quiet).\n"
    "                   Also set via CLAWCODEX_GATEWAY_LOG_LEVEL=INFO|DEBUG.\n"
)


@register("gateway")
def run_gateway_command(args: list[str]) -> int:
    from extensions.im_gateway.server import DaemonPaths, GatewayDaemon

    if not args or args[0] in ("help", "--help", "-h"):
        print(_USAGE)
        return 0

    if args[0] != "server":
        print(f"error: unknown gateway subcommand {args[0]!r}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    rest = args[1:]
    if not rest:
        print(_USAGE)
        return 0

    # Optional --state-dir / --verbose flags.
    state_dir = None
    verbose = False
    verb_args: list[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == "--state-dir" and i + 1 < len(rest):
            state_dir = rest[i + 1]
            i += 2
            continue
        if rest[i] in ("-v", "--verbose"):
            verbose = True
            i += 1
            continue
        verb_args.append(rest[i])
        i += 1

    if not verb_args:
        print(_USAGE)
        return 0
    verb = verb_args[0]
    paths = DaemonPaths.for_state_dir(state_dir)
    daemon = GatewayDaemon(paths)
    if verb == "status":
        return daemon.status()
    if verb == "start":
        return daemon.start(verbose=verbose)
    if verb == "stop":
        return daemon.stop()
    if verb == "restart":
        return daemon.restart(verbose=verbose)
    print(f"error: unknown server verb {verb!r}", file=sys.stderr)
    return 2


__all__ = ["run_gateway_command"]
