"""``remoteControl`` daemon worker.

This worker wraps the multi-session bridge loop in
``extensions.ports.bridge.bridge_main``. It is launched as a
subprocess by the supervisor; ``run(env)`` is the entry point.

The supervisor injects ``CLAWCODEX_DAEMON_*`` environment variables;
this worker translates them into bridge CLI flags and hands them to
``bridge_main()``.

Failure semantics
-----------------
* :class:`extensions.daemon.errors.PermanentWorkerError` → exit
  :data:`EXIT_CODE_PERMANENT`. The supervisor parks the worker.
* Any other exception → exit :data:`EXIT_CODE_TRANSIENT`. The
  supervisor restarts with exponential backoff.
* Clean exit (0) → supervisor treats the worker as stopped (no
  auto-restart under the MVP — restart must be requested via CLI).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

from extensions.daemon.errors import PermanentWorkerError
from extensions.daemon.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class RemoteControlWorker(BaseWorker):
    """Bridge-backed ``remoteControl`` worker."""

    kind = "remoteControl"

    def __init__(self) -> None:
        super().__init__()
        self._cancel: asyncio.Event | None = None

    async def run(self, env: dict[str, str]) -> int:
        cfg = self.read_daemon_env(env)

        # Translate daemon config → bridge CLI flags.
        bridge_args: list[str] = []
        if cfg["spawn_mode"] and cfg["spawn_mode"] != "single-session":
            bridge_args += ["--spawn", cfg["spawn_mode"]]
        if cfg["capacity"] and cfg["capacity"] != 4:
            bridge_args += ["--capacity", str(cfg["capacity"])]
        if cfg["sandbox"]:
            bridge_args += ["--sandbox"]
        else:
            bridge_args += ["--no-sandbox"]
        if cfg["permission_mode"]:
            bridge_args += ["--permission-mode", cfg["permission_mode"]]
        if cfg["name"]:
            bridge_args += ["--name", cfg["name"]]

        # If the supervisor told us to timeout, surface it as a session
        # timeout (seconds) for the bridge loop.
        if cfg["timeout_ms"] and cfg["timeout_ms"] != 30_000:
            bridge_args += ["--session-timeout", str(int(cfg["timeout_ms"] / 1000))]

        # Lazy import — the bridge is heavy and should never be loaded
        # by ``clawcodex-dev --help``.
        try:
            from extensions.ports.bridge.bridge_main import bridge_main
        except ImportError as exc:  # pragma: no cover - guarded import
            logger.error("remoteControl: bridge import failed: %s", exc)
            # Import failure is a configuration problem — permanent.
            return 78

        # Build a cancel event so we can shut down promptly on signal.
        cancel = asyncio.Event()
        self._cancel = cancel
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):  # noqa: F821 — local binding
            try:
                loop.add_signal_handler(sig, cancel.set)
            except (NotImplementedError, RuntimeError):
                # Windows / non-main thread — fall back to default
                # handling. The bridge loop honors its own cancel
                # event for cleanup; supervisors kill via SIGKILL on
                # timeout.
                pass

        try:
            rc = await bridge_main(
                bridge_args,
                working_dir=cfg["dir"] or os.getcwd(),
                cancel_event=cancel,
            )
        except PermanentWorkerError:
            return 78
        except Exception:
            logger.exception("remoteControl: bridge_main failed")
            return 1

        # Translate bridge exit codes:
        #   0 = clean shutdown   → 0
        #   1 = parse error/help → 78 (permanent)
        #   2 = registration     → 1 (transient — retry on next backoff)
        #   3 = permanent runtime→ 78
        if rc == 1:
            return 78
        if rc == 3:
            return 78
        return rc

    def health_check(self) -> dict[str, Any] | None:
        snap = super().health_check() or {}
        snap["has_cancel"] = self._cancel is not None
        return snap


# ``WorkerRegistry.register`` requires a factory, not a class. The
# factory returns a fresh worker on every supervisor spawn cycle so
# each subprocess gets its own state.
def build_remote_control_worker() -> RemoteControlWorker:
    return RemoteControlWorker()


__all__ = ["RemoteControlWorker", "build_remote_control_worker"]
