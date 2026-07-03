"""Constants for the daemon subsystem (F-84).

All exit codes and timing tunables live here so worker implementations
and the supervisor agree on a single set of values. Mirrors the
behavior described in ``docs/feature_plan/06-ccb-benchmark/f-84-daemon.md``
section §1.5 and §1.8.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Exit codes — the worker subprocess reports these to the supervisor.
# ---------------------------------------------------------------------------

#: Worker is signaling a permanent error (do not restart). Matches the
#: BSD sysexits.h ``EX_CONFIG`` code so it reads naturally in shell logs.
EXIT_CODE_PERMANENT: int = 78

#: Transient error — supervisor should restart with exponential backoff.
EXIT_CODE_TRANSIENT: int = 1

#: Normal success — supervisor does NOT auto-restart on 0 unless
#: ``DaemonConfig.autorestart`` is True (currently always False for the
#: MVP — workers that complete cleanly stay stopped).
EXIT_CODE_OK: int = 0

# ---------------------------------------------------------------------------
# Backoff (exponential restart delays).
# ---------------------------------------------------------------------------

#: Initial backoff window before restarting a transient failure.
BACKOFF_INITIAL_MS: int = 2_000

#: Upper bound for the exponential backoff.
BACKOFF_CAP_MS: int = 120_000

#: Multiplier applied to ``BACKOFF_INITIAL_MS`` after each failure.
BACKOFF_MULTIPLIER: int = 2

# ---------------------------------------------------------------------------
# Rapid-failure parking — workers that crash too often in a short window
# are parked (no further restarts) to avoid supervisor thrash.
# ---------------------------------------------------------------------------

#: Threshold of rapid failures that triggers parking.
MAX_RAPID_FAILURES: int = 5

#: Window inside which a failure counts as "rapid".
RAPID_FAILURE_WINDOW_MS: int = 10_000

# ---------------------------------------------------------------------------
# Graceful shutdown.
# ---------------------------------------------------------------------------

#: Default timeout for graceful worker shutdown (SIGTERM → wait → SIGKILL).
GRACEFUL_SHUTDOWN_TIMEOUT_MS: int = 30_000

# ---------------------------------------------------------------------------
# Filesystem layout.
# ---------------------------------------------------------------------------

#: Directory under the user's home that holds daemon state files.
DAEMON_STATE_DIRNAME: str = ".clawcodex"

#: Subdirectory that contains per-daemon state JSON files.
DAEMON_STATE_SUBDIR: str = "daemon"

#: Filename for the per-daemon state JSON file. The name suffix is
#: derived from ``DaemonConfig.name`` (default ``"remote-control"``).
DAEMON_STATE_FILENAME_EXT: str = ".json"

# ---------------------------------------------------------------------------
# Environment variables injected into worker subprocesses.
# ---------------------------------------------------------------------------

ENV_VAR_SUPERVISOR_PID: str = "CLAWCODEX_SUPERVISOR_PID"
ENV_VAR_DAEMON_NAME: str = "CLAWCODEX_DAEMON_NAME"
ENV_VAR_DAEMON_DIR: str = "CLAWCODEX_DAEMON_DIR"
ENV_VAR_DAEMON_SPAWN_MODE: str = "CLAWCODEX_DAEMON_SPAWN_MODE"
ENV_VAR_DAEMON_CAPACITY: str = "CLAWCODEX_DAEMON_CAPACITY"
ENV_VAR_DAEMON_PERMISSION_MODE: str = "CLAWCODEX_DAEMON_PERMISSION_MODE"
ENV_VAR_DAEMON_SANDBOX: str = "CLAWCODEX_DAEMON_SANDBOX"
ENV_VAR_DAEMON_TIMEOUT_MS: str = "CLAWCODEX_DAEMON_TIMEOUT_MS"
ENV_VAR_DAEMON_SESSION_KIND: str = "CLAWCODEX_SESSION_KIND"