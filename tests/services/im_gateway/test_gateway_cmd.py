"""Tests for the Gateway daemon lifecycle (PID/lock/stale socket/health)."""

from __future__ import annotations

import time

import pytest

from extensions.im_gateway.server import (
    DaemonPaths,
    GatewayDaemon,
    cleanup_stale,
    is_pid_alive,
    read_pid,
    acquire_lock,
)


def test_status_not_running(tmp_path) -> None:
    daemon = GatewayDaemon(DaemonPaths.for_state_dir(tmp_path))
    rc = daemon.status()
    assert rc == 0  # not-running is a valid status


def test_stale_socket_cleanup(tmp_path) -> None:
    paths = DaemonPaths.for_state_dir(tmp_path)
    # stale PID pointing at a dead process + a leftover socket
    paths.pid_file.write_text("999999\n", encoding="utf-8")
    paths.sock_file.write_text("", encoding="utf-8")
    assert cleanup_stale(paths) is True
    assert not paths.pid_file.exists()
    assert not paths.sock_file.exists()


def test_stale_socket_kept_when_pid_alive(tmp_path) -> None:
    paths = DaemonPaths.for_state_dir(tmp_path)
    paths.pid_file.write_text(f"{__import__('os').getpid()}\n", encoding="utf-8")
    paths.sock_file.write_text("", encoding="utf-8")
    # current process is alive → not stale
    assert cleanup_stale(paths) is False
    assert paths.pid_file.exists()


def test_acquire_lock_single_instance(tmp_path) -> None:
    paths = DaemonPaths.for_state_dir(tmp_path)
    fd1 = acquire_lock(paths)
    assert fd1 is not None
    fd2 = acquire_lock(paths)
    assert fd2 is None  # already locked
    import os

    os.close(fd1)


def test_is_pid_alive() -> None:
    import os

    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(999999) is False
    assert is_pid_alive(0) is False


@pytest.mark.integration
def test_daemon_start_status_stop_smoke(tmp_path) -> None:
    """Start the real daemon subprocess, verify PID/socket/health, stop it.

    Marked integration (needs subprocess + POSIX UDS). Run in WSL.
    """
    daemon = GatewayDaemon(DaemonPaths.for_state_dir(tmp_path))
    try:
        rc = daemon.start()
        assert rc == 0, f"daemon failed to start; see {daemon.paths.log_file}"
        pid = read_pid(daemon.paths)
        assert pid is not None and is_pid_alive(pid)
        assert daemon.paths.sock_file.exists()
        # health file written
        health = daemon.paths.health_file.read_text(encoding="utf-8")
        assert '"running": true' in health
    finally:
        daemon.stop()
    # after stop, cleaned up
    assert read_pid(daemon.paths) is None or not is_pid_alive(read_pid(daemon.paths))
