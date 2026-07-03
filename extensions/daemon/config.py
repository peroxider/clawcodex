"""Daemon configuration model (F-84).

A single :class:`DaemonConfig` describes everything the supervisor
needs to know to launch its workers — name, working directory,
which worker kinds to spawn, and the per-worker tunables.

We intentionally keep this as a plain dataclass rather than a
pydantic model so the daemon package has zero pydantic dependency.
Validation happens in :meth:`DaemonConfig.validate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from .constants import (
    BACKOFF_CAP_MS,
    BACKOFF_INITIAL_MS,
    GRACEFUL_SHUTDOWN_TIMEOUT_MS,
)
from .errors import InvalidDaemonConfigError

#: Reserved daemon name used when the user doesn't pass ``--name``.
DEFAULT_DAEMON_NAME: str = "remote-control"

#: Default worker kind set when ``--workers`` is omitted.
DEFAULT_WORKER_KINDS: tuple[str, ...] = ("remoteControl",)

#: Default spawn mode passed through to the bridge worker.
DEFAULT_SPAWN_MODE: str = "same-dir"

#: Default per-worker capacity (max concurrent sessions).
DEFAULT_CAPACITY: int = 4

#: Default graceful shutdown timeout (ms).
DEFAULT_TIMEOUT_MS: int = GRACEFUL_SHUTDOWN_TIMEOUT_MS

#: Default backoff lower bound (ms).
DEFAULT_BACKOFF_INITIAL_MS: int = BACKOFF_INITIAL_MS

#: Default backoff upper bound (ms).
DEFAULT_BACKOFF_CAP_MS: int = BACKOFF_CAP_MS


@dataclass(frozen=True)
class DaemonConfig:
    """Immutable daemon configuration.

    Attributes:
        name: Logical daemon instance name. Defaults to
            :data:`DEFAULT_DAEMON_NAME`. Used to namespace the state
            file under ``~/.clawcodex/daemon/<name>.json``.
        dir: Working directory passed to spawned workers (their
            ``cwd``). Defaults to the current working directory at
            construction time.
        worker_kinds: Tuple of worker kinds to spawn (e.g.
            ``("remoteControl",)``). Order is preserved — workers are
            started left-to-right.
        spawn_mode: Spawn mode forwarded to the bridge worker.
            One of ``"single-session"``, ``"worktree"``, ``"same-dir"``.
        capacity: Max concurrent sessions per worker.
        permission_mode: Optional permission mode override forwarded to
            workers (e.g. ``"bypassPermissions"``, ``"dontAsk"``).
        sandbox: If True, workers run with sandboxing enabled.
        timeout_ms: Graceful shutdown timeout for each worker.
        backoff_initial_ms: Initial backoff between restart attempts.
        backoff_cap_ms: Upper bound on the exponential backoff.
        log_level: Log level for supervisor and worker output.
        extra_env: Extra environment variables to inject into every
            spawned worker (e.g. provider credentials).
    """

    name: str = DEFAULT_DAEMON_NAME
    dir: Path = field(default_factory=Path.cwd)
    worker_kinds: tuple[str, ...] = DEFAULT_WORKER_KINDS
    spawn_mode: str = DEFAULT_SPAWN_MODE
    capacity: int = DEFAULT_CAPACITY
    permission_mode: str | None = None
    sandbox: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    backoff_initial_ms: int = DEFAULT_BACKOFF_INITIAL_MS
    backoff_cap_ms: int = DEFAULT_BACKOFF_CAP_MS
    log_level: str = "INFO"
    extra_env: tuple[tuple[str, str], ...] = ()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`InvalidDaemonConfigError` on bad input.

        Called automatically by the supervisor and CLI before any
        subprocess is spawned. Tests call it explicitly to exercise
        the boundary conditions.
        """
        if not self.name or not self.name.strip():
            raise InvalidDaemonConfigError("name must be non-empty")
        if "/" in self.name or "\\" in self.name or ".." in self.name:
            raise InvalidDaemonConfigError(
                f"name must not contain path separators or '..': {self.name!r}"
            )
        if not self.worker_kinds:
            raise InvalidDaemonConfigError("worker_kinds must list at least one kind")
        if any(not k or not k.strip() for k in self.worker_kinds):
            raise InvalidDaemonConfigError("worker_kinds entries must be non-empty")
        if self.spawn_mode not in {"single-session", "worktree", "same-dir"}:
            raise InvalidDaemonConfigError(
                f"spawn_mode must be one of single-session/worktree/same-dir, got {self.spawn_mode!r}"
            )
        if self.capacity < 1:
            raise InvalidDaemonConfigError("capacity must be >= 1")
        if self.timeout_ms < 1_000:
            raise InvalidDaemonConfigError("timeout_ms must be >= 1000")
        if self.backoff_initial_ms < 1:
            raise InvalidDaemonConfigError("backoff_initial_ms must be >= 1")
        if self.backoff_cap_ms < self.backoff_initial_ms:
            raise InvalidDaemonConfigError(
                "backoff_cap_ms must be >= backoff_initial_ms"
            )

    # ------------------------------------------------------------------
    # Ergonomics — frozen dataclasses can't be mutated, so we offer
    # ``with_*`` helpers that return new instances.
    # ------------------------------------------------------------------

    def with_workers(self, kinds: Iterable[str]) -> "DaemonConfig":
        return replace(self, worker_kinds=tuple(kinds))

    def with_dir(self, dir_: Path) -> "DaemonConfig":
        return replace(self, dir=Path(dir_).resolve())

    def with_name(self, name: str) -> "DaemonConfig":
        return replace(self, name=name)