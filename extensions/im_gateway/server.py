"""Gateway daemon lifecycle: PID/lock, stale-socket cleanup, health.

The daemon process runs :func:`serve` under ``asyncio.run``: it creates
a :class:`MessageGateway`, opens a POSIX UDS listener (``UdsPipeServer``
as the line-protocol base; ``GatewayIpcProtocol`` semantics land in
P2/P3), writes a PID file + health file, installs SIGTERM/SIGINT
handlers for graceful shutdown, and serves until stopped.

``clawcodex-dev gateway server start|stop|status|restart`` (in
``gateway_cmd/commands.py``) calls :class:`GatewayDaemon` which spawns
``python -m extensions.im_gateway.server serve`` as a detached
subprocess. ``status`` reads the PID + health file; ``stop`` sends
SIGTERM. v1 acceptance is POSIX/WSL/Git Bash only.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from clawcodex_ext.services.im_gateway.config import (
    DEFAULT_STATE_DIR,
    load_config,
    migrate_legacy_state_dir,
)
from clawcodex_ext.services.im_gateway.gateway import MessageGateway

logger = logging.getLogger(__name__)

# ``DEFAULT_STATE_DIR`` is re-exported from
# :mod:`clawcodex_ext.services.im_gateway.config` (imported above) so the
# historical ``from extensions.im_gateway.server import DEFAULT_STATE_DIR``
# import keeps working.


@dataclass
class DaemonPaths:
    state_dir: Path
    pid_file: Path
    lock_file: Path
    sock_file: Path
    health_file: Path
    log_file: Path

    @classmethod
    def for_state_dir(cls, state_dir: str | Path | None = None) -> DaemonPaths:
        if state_dir is None:
            # Move a pre-rename ~/.clawcodex/im-gateway install forward the
            # first time the default path is resolved.
            base = migrate_legacy_state_dir()
        else:
            base = Path(state_dir).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return cls(
            state_dir=base,
            pid_file=base / 'gateway.pid',
            lock_file=base / 'gateway.lock',
            sock_file=base / 'gateway.sock',
            health_file=base / 'health.json',
            log_file=base / 'gateway.log',
        )


# -- process helpers -----------------------------------------------------


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def read_pid(paths: DaemonPaths) -> int | None:
    if not paths.pid_file.exists():
        return None
    try:
        return int(paths.pid_file.read_text(encoding='utf-8').strip())
    except (ValueError, OSError):
        return None


def write_pid(paths: DaemonPaths, pid: int) -> None:
    paths.pid_file.write_text(f'{pid}\n', encoding='utf-8')


def cleanup_stale(paths: DaemonPaths) -> bool:
    """Remove stale PID + socket if the recorded PID is dead.

    Returns True if any stale artifact was removed.
    """
    removed = False
    pid = read_pid(paths)
    if pid is not None and not is_pid_alive(pid):
        with contextlib.suppress(FileNotFoundError):
            paths.pid_file.unlink()
        removed = True
    if paths.sock_file.exists():
        # A socket without a live PID is stale.
        if pid is None or not is_pid_alive(pid):
            with contextlib.suppress(FileNotFoundError):
                paths.sock_file.unlink()
            removed = True
    return removed


def acquire_lock(paths: DaemonPaths) -> int | None:
    """Try to acquire the single-instance lock. Returns fd or None."""
    paths.lock_file.parent.mkdir(parents=True, exist_ok=True)
    paths.lock_file.touch(exist_ok=True)
    fd = os.open(str(paths.lock_file), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def write_health(paths: DaemonPaths, **fields) -> None:
    data = {
        'running': True,
        'pid': os.getpid(),
        'started_at': fields.get('started_at', time.time()),
        'channels': fields.get('channels', []),
        'state_dir': str(paths.state_dir),
        'socket': str(paths.sock_file),
    }
    paths.health_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def read_health(paths: DaemonPaths) -> dict | None:
    if not paths.health_file.exists():
        return None
    try:
        return json.loads(paths.health_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


# -- daemon process ------------------------------------------------------


def _resolve_log_level(verbose: bool, env: str | None) -> int:
    """Pick the daemon log level.

    Priority: ``CLAWCODEX_GATEWAY_LOG_LEVEL`` env > ``CLAWCODEX_DEBUG=1``
    (DEBUG) > ``--verbose`` flag (DEBUG) > default (WARNING). Pass
    ``--verbose`` or set ``CLAWCODEX_DEBUG=1`` during diagnosis; set
    ``CLAWCODEX_GATEWAY_LOG_LEVEL`` to pin a specific level.
    """
    if env:
        env = env.strip().upper()
        levels = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
        }
        if env in levels:
            return levels[env]
    if os.environ.get('CLAWCODEX_DEBUG', '').lower() in ('1', 'true', 'yes'):
        return logging.DEBUG
    if verbose:
        return logging.DEBUG
    return logging.WARNING


async def serve(paths: DaemonPaths, *, log_level: int = logging.WARNING) -> int:
    """Run the gateway daemon (called from the spawned subprocess)."""
    # Configure logging FIRST with a RotatingFileHandler (10 MiB per file,
    # keep up to 3 backups so the log never exceeds ~40 MiB). The subprocess
    # stderr is still redirected to the same log file by GatewayDaemon.start,
    # capturing any unhandled crash dumps that bypass the logging framework.
    os.makedirs(paths.log_file.parent, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(log_level)
    handler = logging.handlers.RotatingFileHandler(
        str(paths.log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MiB
        backupCount=3,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    handler.setLevel(log_level)
    # Replace any existing handlers so the daemon subprocess owns its logging.
    root.handlers.clear()
    root.addHandler(handler)
    # Channel + gateway internals follow the resolved level; keep noisy libs
    # at WARNING so urllib/asyncio don't flood the log.
    logging.getLogger('clawcodex_ext.services.channels').setLevel(log_level)
    logging.getLogger('clawcodex_ext.services.im_gateway').setLevel(log_level)

    fd = acquire_lock(paths)
    if fd is None:
        print('error: another gateway daemon holds the lock', file=sys.stderr)
        return 1
    cleanup_stale(paths)

    config = load_config(paths.state_dir / 'channels.yaml')
    # Force the gateway's reliability store to live under the daemon's
    # state_dir (the YAML default points at ~/.clawcodex/gateway).
    config.state_dir = str(paths.state_dir)
    gateway = MessageGateway(config)
    await gateway.start()
    # Register the unbound-origin handler so authorized messages get explicit
    # REPL/orchestrator connection guidance instead of being silently dropped.
    from clawcodex_ext.services.im_gateway.stub_agent import make_stub_handler

    gateway.set_handler(make_stub_handler(gateway.outbound))
    logger.info('gateway inbound handler registered: unbound guidance handler')

    # Open the GatewayIpcProtocol UDS listener (register/heartbeat/deliver/ack
    # + control reload/status). P2/P3 frames are handled by GatewayIpcServer.
    from clawcodex_ext.services.im_gateway.ipc_server import GatewayIpcServer

    server = GatewayIpcServer(paths.sock_file, gateway)
    await server.start()

    # Wire the opt-in push path: when an origin is bound to a REPL/orchestrator
    # peer, the dispatcher pushes inbound messages over IPC instead of the
    # stub handler. The push callback delegates to the IPC server.
    async def _push_to_opt_in(message) -> bool:
        return await server.push_deliver(
            origin=message.origin,
            delivery_id=message.message_id,
            text=message.text,
            semantic=message.semantic.value if message.semantic else None,
        )

    gateway.set_push_handler(_push_to_opt_in)
    logger.info('gateway opt-in push handler registered')

    started_at = time.time()
    write_pid(paths, os.getpid())
    write_health(paths, started_at=started_at, channels=gateway.registry.names())

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _schedule_shutdown(sig_name: str) -> None:
        asyncio.create_task(_shutdown(server, gateway, paths, stop_event, sig_name))

    for sig in (signal.SIGTERM, signal.SIGINT):
        sig_name = signal.Signals(sig).name
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _schedule_shutdown, sig_name)

    await stop_event.wait()
    os.close(fd)
    return 0


async def _shutdown(
    server, gateway, paths: DaemonPaths, stop_event: asyncio.Event, sig_name: str
) -> None:
    await server.close()
    await gateway.stop()
    with contextlib.suppress(FileNotFoundError):
        paths.pid_file.unlink()
    with contextlib.suppress(FileNotFoundError):
        paths.health_file.unlink()
    with contextlib.suppress(FileNotFoundError):
        paths.sock_file.unlink()
    stop_event.set()


# -- CLI-facing controller ----------------------------------------------


class GatewayDaemon:
    """Controls the gateway daemon subprocess from the CLI."""

    def __init__(self, paths: DaemonPaths | None = None) -> None:
        self.paths = paths or DaemonPaths.for_state_dir()

    def status(self) -> int:
        pid = read_pid(self.paths)
        if pid is None or not is_pid_alive(pid):
            print('Gateway daemon: NOT RUNNING')
            if pid is not None:
                print(f'  (stale PID {pid}; cleaned up)')
                cleanup_stale(self.paths)
            return 0
        health = read_health(self.paths) or {}
        uptime_s = int(time.time() - health.get('started_at', time.time()))
        print('Gateway daemon: RUNNING')
        print(f'  PID            : {pid}')
        print(f'  Uptime         : {uptime_s}s')
        print(f'  Socket         : {self.paths.sock_file}')
        print(f'  Log            : {self.paths.log_file}')
        print(f'  Channels       : {", ".join(health.get("channels") or []) or "(none)"}')
        print(f'  State dir      : {self.paths.state_dir}')
        return 0

    def start(self, *, verbose: bool = False) -> int:
        pid = read_pid(self.paths)
        if pid is not None and is_pid_alive(pid):
            print(f'Gateway daemon already running (PID {pid}).')
            return self.status()
        cleanup_stale(self.paths)
        # Attach the log file as the subprocess's stdout+stderr so any
        # unhandled crash dumps that bypass the logging framework are captured.
        # RotatingFileHandler inside serve() handles normal log rotation.
        log_fh = self.paths.log_file.open('a', encoding='utf-8')
        serve_args = [
            sys.executable,
            '-m',
            'extensions.im_gateway.server',
            'serve',
            '--state-dir',
            str(self.paths.state_dir),
        ]
        if verbose:
            serve_args.append('--verbose')
        proc = subprocess.Popen(
            serve_args,
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Wait for the daemon to write its PID file (best-effort, bounded).
        deadline = time.time() + 10.0
        while time.time() < deadline:
            new_pid = read_pid(self.paths)
            if new_pid is not None and is_pid_alive(new_pid):
                print(f'Gateway daemon started · pid {new_pid}')
                return 0
            if proc.poll() is not None:
                print(
                    f'error: gateway daemon exited early (code {proc.returncode}); see {self.paths.log_file}',
                    file=sys.stderr,
                )
                return 1
            time.sleep(0.1)
        print('error: gateway daemon did not become ready in 10s', file=sys.stderr)
        return 1

    def stop(self, *, timeout: float = 5.0) -> int:
        pid = read_pid(self.paths)
        if pid is None or not is_pid_alive(pid):
            print('Gateway daemon: already stopped')
            cleanup_stale(self.paths)
            return 0
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            cleanup_stale(self.paths)
            return 0
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not is_pid_alive(pid):
                break
            time.sleep(0.1)
        if is_pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
        cleanup_stale(self.paths)
        print('Gateway daemon stopped.')
        return 0

    def restart(self, *, verbose: bool = False) -> int:
        rc_stop = self.stop()
        if rc_stop != 0:
            return rc_stop
        return self.start(verbose=verbose)


# -- entry point ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='extensions.im_gateway.server')
    sub = parser.add_subparsers(dest='cmd', required=True)
    serve_p = sub.add_parser('serve', help='run the daemon (foreground)')
    serve_p.add_argument('--state-dir', default=None)
    serve_p.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help='enable DEBUG-level IM logging (default: WARNING; use --verbose or set '
        'CLAWCODEX_GATEWAY_LOG_LEVEL=INFO|DEBUG)',
    )
    args = parser.parse_args(argv)
    if args.cmd == 'serve':
        paths = DaemonPaths.for_state_dir(args.state_dir)
        log_level = _resolve_log_level(args.verbose, os.environ.get('CLAWCODEX_GATEWAY_LOG_LEVEL'))
        try:
            return asyncio.run(serve(paths, log_level=log_level))
        except KeyboardInterrupt:
            return 0
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
