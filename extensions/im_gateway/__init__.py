"""IM Message Gateway daemon process.

Hosts :class:`MessageGateway` as a long-running daemon, listening on a
POSIX UDS socket for REPL/orchestrator opt-in clients. Lifecycle is
managed by ``clawcodex-dev gateway server start|stop|status|restart``
via :mod:`clawcodex_ext.cli.gateway_cmd`.

v1 (P1) ships lifecycle + PID/lock/stale-socket/health. WeChat adapter
hosting lands in P2; the full ``GatewayIpcProtocol`` listener + agent
registry in P2/P3; reliability hardening in P4; default host agent in P5.
"""
