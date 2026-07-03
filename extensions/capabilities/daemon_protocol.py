"""Daemon subsystem Protocol — Worker contract.

The ``Worker`` Protocol defines the surface the supervisor uses to
interact with a daemon worker. Concrete implementations live in
``extensions/daemon/workers/`` and are registered through
``extensions.daemon.worker_registry.WorkerRegistry``.

Design notes
------------
* The Protocol is ``@runtime_checkable`` so callers can use
  ``isinstance(worker, Worker)`` for cheap contract checks without
  having to import a concrete base class.
* The Protocol takes the worker's environment as a plain
  ``dict[str, str]`` rather than a pydantic model — this matches the
  way ``subprocess.Popen`` consumes ``env=`` arguments and keeps the
  surface portable across ``src/`` and ``extensions/``.
* ``health_check()`` is optional — the Protocol declares it but does
  not require implementations to override it. Supervisors call it
  defensively (``getattr`` or ``hasattr``) so missing overrides are
  silently tolerated.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Worker(Protocol):
    """Subprocess-side worker entry point.

    A worker is a Python class instantiated inside the worker
    subprocess launched by the supervisor. The supervisor passes a
    prepared environment (with ``CLAWCODEX_DAEMON_*`` variables set)
    and the worker's ``run`` coroutine drives the work until it
    exits.

    Exit semantics:

    * ``0``  — normal completion. Supervisor treats this as "stopped,
      not failed" unless configured otherwise.
    * :data:`EXIT_CODE_PERMANENT` (78) — permanent failure. Supervisor
      parks the worker (no further restarts).
    * Any other code — transient failure. Supervisor restarts after
      the current backoff window.
    """

    #: Logical worker kind — must match the registration key under
    #: :class:`extensions.daemon.worker_registry.WorkerRegistry`.
    kind: str

    async def run(self, env: dict[str, str]) -> int:
        """Worker main loop.

        Args:
            env: The merged environment for the worker subprocess.
                Includes both the supervisor's environment and any
                ``DAEMON_*`` overrides.

        Returns:
            Exit code. ``0`` for success, ``78`` for permanent
            failure, anything else for transient failure.
        """
        ...

    def health_check(self) -> dict[str, Any] | None:
        """Optional health snapshot.

        Returns a JSON-serializable dict describing the worker's
        current health (PID, uptime, last error, etc.) or ``None`` if
        the worker doesn't expose one. Supervisors and the RCS
        dashboard call this defensively.
        """
        ...


__all__ = ["Worker"]
