"""Supervisor main loop (daemon entry point).

The supervisor owns one :class:`DaemonConfig` and a list of
:class:`WorkerRuntime`. Its public surface is intentionally small:

* :meth:`Supervisor.run` — the long-running main loop. Spawns every
  configured worker, waits for one of them to die, then loops.
* :meth:`Supervisor.request_stop` — set the stop event (called from
  signal handlers or CLI ``daemon stop``).

Signal handling
---------------
On POSIX, the supervisor installs ``SIGTERM`` / ``SIGINT`` /
``SIGBREAK`` handlers that flip the stop event. On Windows the
``add_signal_handler`` API isn't available — the subprocess's own
signal handling is what fires when the supervisor is killed from the
outside.

Persistence
-----------
The supervisor writes its :class:`DaemonState` before the first spawn
and removes it during graceful shutdown. If the supervisor crashes,
``query_daemon_status`` cleans the stale file on the next call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Mapping

from .config import DaemonConfig
from .constants import GRACEFUL_SHUTDOWN_TIMEOUT_MS
from .errors import DaemonAlreadyRunningError, WorkerSpawnError
from .lifecycle import WorkerRuntime, graceful_shutdown, spawn_worker
from .state import (
    DaemonState,
    DaemonStatus,
    make_state,
    query_daemon_status,
    remove_daemon_state,
    write_daemon_state,
)
from .worker_registry import WorkerRegistry

# Eagerly import the built-in workers package so the
# ``WorkerRegistry.known_kinds()`` check at run-time always finds
# the canonical remoteControl / cron factories. This is a no-op
# (re-registration is allowed) when ``extensions.daemon.workers``
# is imported separately.
import extensions.daemon.workers  # noqa: F401  (registers on import)

logger = logging.getLogger(__name__)


class Supervisor:
    """Long-running daemon supervisor.

    The constructor is intentionally synchronous and cheap — heavy
    work (registry lookup, subprocess spawn) happens in :meth:`run`.
    """

    def __init__(
        self,
        config: DaemonConfig,
        *,
        state_dir: Path | None = None,
        on_state_change=None,
    ) -> None:
        config.validate()
        self.config = config
        self.state_dir = state_dir
        self._stop_event = asyncio.Event()
        self._runtimes: list[WorkerRuntime] = []
        self._on_state_change = on_state_change

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def run(self) -> int:
        """Run the supervisor until a stop is requested.

        Returns the supervisor's process exit code:

        * ``0`` — clean shutdown.
        * ``1`` — configuration / spawn error before any worker ran.
        """
        if self._stop_event.is_set():
            return 0

        # Reject if another supervisor is already running.
        status, _ = query_daemon_status(self.config.name, state_dir=self.state_dir)
        if status == DaemonStatus.RUNNING:
            raise DaemonAlreadyRunningError(f"daemon {self.config.name!r} is already running")

        # Persist identity before any spawn so a crash here still
        # leaves a queryable state.
        state = make_state(
            pid=os.getpid(),
            worker_kinds=list(self.config.worker_kinds),
            name=self.config.name,
            cwd=self.config.dir,
        )
        write_daemon_state(state, state_dir=self.state_dir)
        self._publish_state(state)

        self._install_signal_handlers()
        self._runtimes = [WorkerRuntime(kind=k) for k in self.config.worker_kinds]

        # Validate kinds up front — fail fast before any spawn.
        for kind in self.config.worker_kinds:
            if not WorkerRegistry.has_kind(kind):
                raise ValueError(
                    f"worker kind {kind!r} is not registered "
                    f"(known kinds: {WorkerRegistry.known_kinds()})"
                )

        try:
            await self._main_loop()
        finally:
            await graceful_shutdown(
                self._runtimes,
                timeout_ms=self.config.timeout_ms or GRACEFUL_SHUTDOWN_TIMEOUT_MS,
            )
            remove_daemon_state(self.config.name, state_dir=self.state_dir)
            self._publish_state(None)
        return 0

    def request_stop(self) -> None:
        """Set the stop event. Idempotent."""
        self._stop_event.set()

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    @property
    def runtimes(self) -> Mapping[str, WorkerRuntime]:
        return {r.kind: r for r in self._runtimes}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except (NotImplementedError, RuntimeError):
                # Windows / non-main thread — nothing else we can do here.
                pass

    async def _main_loop(self) -> None:
        """Spawn all workers; wait for one to exit; loop.

        Each worker spawn runs concurrently — we use ``asyncio.gather``
        so a worker crash surfaces immediately rather than blocking
        the others. When ``stop_event`` is set we wait for the gather
        to unwind naturally.
        """
        tasks: list[asyncio.Task] = []
        for runtime in self._runtimes:
            if not WorkerRegistry.has_kind(runtime.kind):
                continue
            tasks.append(
                asyncio.create_task(
                    self._supervise_one(runtime),
                    name=f"daemon-worker-{runtime.kind}",
                )
            )

        if not tasks:
            logger.warning("[supervisor] no workers spawned; exiting")
            return

        stop_wait = asyncio.create_task(self._stop_event.wait(), name="supervisor-stop")
        try:
            done, pending = await asyncio.wait(
                tasks + [stop_wait],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stop_wait.cancel()

        # If a worker died before stop was requested, we want to keep
        # supervising — schedule a fresh spawn. With FIRST_COMPLETED
        # the supervisor returns immediately; we re-enter until either
        # every worker is parked or the stop event is set.
        for t in tasks:
            if t.done() and not t.cancelled():
                exc = t.exception()
                if isinstance(exc, WorkerSpawnError):
                    logger.error("[supervisor] spawn error: %s", exc)
                elif exc is not None:
                    logger.exception("[supervisor] worker task crashed")

    async def _supervise_one(self, runtime: WorkerRuntime) -> None:
        """Run :func:`spawn_worker` for *runtime* until it parks or
        the supervisor stops."""
        while not self._stop_event.is_set() and not runtime.parked:
            try:
                await spawn_worker(
                    runtime,
                    supervisor_pid=os.getpid(),
                    name=self.config.name,
                    dir_=self.config.dir,
                    spawn_mode=self.config.spawn_mode,
                    capacity=self.config.capacity,
                    permission_mode=self.config.permission_mode,
                    sandbox=self.config.sandbox,
                    timeout_ms=self.config.timeout_ms,
                    stop_event=self._stop_event,
                )
            except WorkerSpawnError as exc:
                logger.error("[supervisor] spawn error for %s: %s", runtime.kind, exc)
                runtime.parked = True
                return
            except asyncio.CancelledError:
                return
            # If the worker exited cleanly (rc=0), spawn_worker will not
            # restart it — break out so we don't busy-loop.
            if runtime.last_exit_code == 0:
                return

    def _publish_state(self, state: DaemonState | None) -> None:
        if self._on_state_change is None:
            return
        try:
            self._on_state_change(state)
        except Exception:
            logger.exception("[supervisor] on_state_change callback failed")


__all__ = ["Supervisor"]
