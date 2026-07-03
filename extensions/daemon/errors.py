"""Custom exceptions raised by the daemon subsystem (F-84)."""

from __future__ import annotations


class DaemonError(Exception):
    """Base class for all F-84 daemon errors.

    Catching ``DaemonError`` covers every error this subsystem emits so
    callers (orchestrator, RCS, CLI) can fail safely without enumerating
    each subclass.
    """


class UnknownWorkerKindError(DaemonError, KeyError):
    """The requested worker kind is not registered.

    Inherits from :class:`KeyError` so handlers that already test
    ``except KeyError`` (e.g. dict-style lookups) keep working.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(f"unknown worker kind: {kind!r}")
        self.kind = kind


class PermanentWorkerError(DaemonError):
    """Signal from a worker that it should not be restarted.

    Workers raise this from inside their ``run()`` coroutine when they
    hit a permanent failure (bad config, missing credentials, etc.).
    The supervisor catches it, parks the worker, and exits with
    :data:`EXIT_CODE_PERMANENT`.
    """

    def __init__(self, message: str = "permanent worker failure") -> None:
        super().__init__(message)


class WorkerSpawnError(DaemonError):
    """The supervisor failed to spawn a worker subprocess.

    Usually wraps ``FileNotFoundError`` (Python interpreter missing),
    ``PermissionError`` (executable not runnable), or OS-level errors
    such as ``OSError(EAGAIN)`` when the process table is exhausted.
    """


class DaemonAlreadyRunningError(DaemonError):
    """``daemon start`` refused because another instance owns the state file.

    The caller should run ``daemon stop`` first, or pass
    ``--force`` if F-84 ever grows that option.
    """


class DaemonNotRunningError(DaemonError):
    """``daemon stop`` / ``daemon status`` called but no live daemon found."""


class InvalidDaemonConfigError(DaemonError, ValueError):
    """``DaemonConfig`` failed validation.

    Inherits from :class:`ValueError` for handlers that already catch
    validation errors generically.
    """