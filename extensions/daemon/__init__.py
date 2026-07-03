"""F-84 Daemon — long-running supervisor for worker subprocesses.

This package implements the ClawCodex counterpart of CCB's
``src/daemon/main.ts`` supervisor. The supervisor process owns a
collection of *workers* (typically the remote-control bridge, but
also future cron / orchestrator hosts) and restarts them with
exponential backoff when they crash.

Layout::

    extensions/daemon/
    ├── __init__.py           ← public surface (this file)
    ├── constants.py          ← exit codes + timing tunables
    ├── errors.py             ← exception types
    ├── config.py             ← DaemonConfig dataclass
    ├── state.py              ← state-file IO + liveness probe
    ├── worker_registry.py    ← kind → factory registry
    ├── lifecycle.py          ← spawn / restart / graceful shutdown
    ├── supervisor.py         ← Supervisor main loop
    ├── worker_main.py        ← `python -m extensions.daemon.worker_main <kind>`
    ├── cli.py                ← `clawcodex-dev daemon <verb>` CLI
    └── workers/
        ├── __init__.py
        ├── base.py           ← Worker base class
        ├── remote_control.py ← remoteControl Worker (bridge wrapper)
        └── cron.py           ← cron Worker (stub)

Importing this package MUST be cheap — ``extensions.daemon`` is
already pulled in by ``clawcodex-dev --help`` indirectly through
``subcommand_registry``. Keep heavy imports inside
:func:`run_daemon_cli` or under ``if __name__ == "__main__"``.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Public surface — re-export only the lightweight names that callers
# might want without touching the heavier lifecycle/supervisor modules.
from .config import (
    DEFAULT_DAEMON_NAME,
    DEFAULT_WORKER_KINDS,
    DaemonConfig,
)
from .constants import (
    BACKOFF_CAP_MS,
    BACKOFF_INITIAL_MS,
    BACKOFF_MULTIPLIER,
    EXIT_CODE_PERMANENT,
    EXIT_CODE_TRANSIENT,
    GRACEFUL_SHUTDOWN_TIMEOUT_MS,
    MAX_RAPID_FAILURES,
    RAPID_FAILURE_WINDOW_MS,
)
from .errors import (
    DaemonAlreadyRunningError,
    DaemonError,
    DaemonNotRunningError,
    InvalidDaemonConfigError,
    PermanentWorkerError,
    UnknownWorkerKindError,
    WorkerSpawnError,
)
from .state import (
    DaemonState,
    DaemonStatus,
    get_state_dir,
    get_state_path,
    is_process_alive,
    make_state,
    query_daemon_status,
    read_daemon_state,
    remove_daemon_state,
    write_daemon_state,
)
from .supervisor import Supervisor
from .worker_registry import WorkerRegistry

__all__ = [
    # version
    "__version__",
    # config
    "DaemonConfig",
    "DEFAULT_DAEMON_NAME",
    "DEFAULT_WORKER_KINDS",
    # constants
    "BACKOFF_CAP_MS",
    "BACKOFF_INITIAL_MS",
    "BACKOFF_MULTIPLIER",
    "EXIT_CODE_PERMANENT",
    "EXIT_CODE_TRANSIENT",
    "GRACEFUL_SHUTDOWN_TIMEOUT_MS",
    "MAX_RAPID_FAILURES",
    "RAPID_FAILURE_WINDOW_MS",
    # errors
    "DaemonAlreadyRunningError",
    "DaemonError",
    "DaemonNotRunningError",
    "InvalidDaemonConfigError",
    "PermanentWorkerError",
    "UnknownWorkerKindError",
    "WorkerSpawnError",
    # state
    "DaemonState",
    "DaemonStatus",
    "get_state_dir",
    "get_state_path",
    "is_process_alive",
    "make_state",
    "query_daemon_status",
    "read_daemon_state",
    "remove_daemon_state",
    "write_daemon_state",
    # supervisor
    "Supervisor",
    # registry
    "WorkerRegistry",
]