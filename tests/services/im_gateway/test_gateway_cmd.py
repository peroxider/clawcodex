"""Tests for the Gateway daemon lifecycle (PID/lock/stale socket/health)
and CLI routing for the flattened `gateway` command."""

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
from clawcodex_ext.cli.gateway_cmd.commands import run_gateway_command


def test_status_not_running(tmp_path) -> None:
    daemon = GatewayDaemon(DaemonPaths.for_state_dir(tmp_path))
    rc = daemon.status()
    assert rc == 0  # not-running is a valid status


def test_stale_socket_cleanup(tmp_path) -> None:
    paths = DaemonPaths.for_state_dir(tmp_path)
    # stale PID pointing at a dead process + a leftover socket
    paths.pid_file.write_text('999999\n', encoding='utf-8')
    paths.sock_file.write_text('', encoding='utf-8')
    assert cleanup_stale(paths) is True
    assert not paths.pid_file.exists()
    assert not paths.sock_file.exists()


def test_stale_socket_kept_when_pid_alive(tmp_path) -> None:
    paths = DaemonPaths.for_state_dir(tmp_path)
    paths.pid_file.write_text(f'{__import__("os").getpid()}\n', encoding='utf-8')
    paths.sock_file.write_text('', encoding='utf-8')
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
        assert rc == 0, f'daemon failed to start; see {daemon.paths.log_file}'
        pid = read_pid(daemon.paths)
        assert pid is not None and is_pid_alive(pid)
        assert daemon.paths.sock_file.exists()
        # health file written
        health = daemon.paths.health_file.read_text(encoding='utf-8')
        assert '"running": true' in health
    finally:
        daemon.stop()
    # after stop, cleaned up
    assert read_pid(daemon.paths) is None or not is_pid_alive(read_pid(daemon.paths))


# -- flattened gateway routing ------------------------------------------------


def test_gateway_no_args_prints_usage(capsys) -> None:
    """`gateway` (no args) prints usage and returns 0."""
    rc = run_gateway_command([])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'usage:' in out


def test_gateway_help_prints_usage(capsys) -> None:
    """`gateway help` prints usage and returns 0."""
    rc = run_gateway_command(['help'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'usage:' in out


def test_gateway_unknown_subcommand_errors(capsys) -> None:
    """`gateway <unknown>` reports an error."""
    rc = run_gateway_command(['bogus'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'unknown gateway subcommand' in err


def test_gateway_server_start_errors(capsys) -> None:
    """`gateway server start` is no longer valid — 'server' is an unknown verb."""
    rc = run_gateway_command(['server', 'start'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'unknown gateway subcommand' in err


def test_gateway_channels_status_errors(capsys) -> None:
    """`gateway channels status` is no longer valid — 'channels' is an unknown verb."""
    rc = run_gateway_command(['channels', 'status'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'unknown gateway subcommand' in err


def test_gateway_start_with_name_errors(capsys) -> None:
    """`gateway start <name>` is invalid — start takes no channel name."""
    rc = run_gateway_command(['start', 'wechat'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'start takes no channel name' in err.lower()


def test_gateway_stop_with_name_errors(capsys) -> None:
    """`gateway stop <name>` is invalid — stop takes no channel name."""
    rc = run_gateway_command(['stop', 'wechat'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'stop takes no channel name' in err.lower()


def test_gateway_setup_calls_wizard(monkeypatch) -> None:
    """`gateway setup` calls run_wizard(None)."""
    called: list[str | None] = []

    def _fake_wizard(path: str | None = None, *, input_fn=None) -> int:
        called.append(path)
        return 0

    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, 'run_wizard', _fake_wizard)
    rc = run_gateway_command(['setup'])
    assert rc == 0
    assert called == [None]


def test_gateway_restart_channel(monkeypatch) -> None:
    """`gateway restart <name>` calls restart_channel."""
    calls: list[tuple] = []

    def _fake_restart(name: str, *, state_dir: str | None = None) -> int:
        calls.append((name, state_dir))
        return 0

    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, 'restart_channel', _fake_restart)
    rc = run_gateway_command(['restart', 'wechat'])
    assert rc == 0
    assert calls == [('wechat', None)]


def test_gateway_restart_daemon(monkeypatch) -> None:
    """`gateway restart` (no name) calls daemon.restart."""
    calls: list[bool] = []

    class _FakeDaemon:
        def __init__(self, *a, **kw):
            pass

        def restart(self, verbose=False):
            calls.append(verbose)
            return 0

    monkeypatch.setattr('extensions.im_gateway.server.GatewayDaemon', _FakeDaemon)
    rc = run_gateway_command(['restart'])
    assert rc == 0
    assert calls == [False]


def test_gateway_status_channel(monkeypatch, capsys) -> None:
    """`gateway status <name>` calls format_status for that name."""
    calls: list[tuple] = []

    def _fake_format_status(path=None, name=None, *, state_dir=None) -> str:
        calls.append((path, name, state_dir))
        return f'STATUS:{name}'

    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, 'format_status', _fake_format_status)
    rc = run_gateway_command(['status', 'wechat'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'STATUS:wechat' in out
    assert calls == [(None, 'wechat', None)]


def test_gateway_status_unified(monkeypatch, capsys) -> None:
    """Bare `gateway status` prints daemon status THEN all-channels status."""
    daemon_status_calls: list[int] = []
    format_status_calls: list[tuple] = []

    class _FakeDaemon:
        def __init__(self, *a, **kw):
            pass

        def status(self):
            daemon_status_calls.append(1)
            print('DAEMON: running', end='')
            return 0

    def _fake_format_status(path=None, name=None, *, state_dir=None) -> str:
        format_status_calls.append((path, name, state_dir))
        return 'CHANNELS: all'

    monkeypatch.setattr('extensions.im_gateway.server.GatewayDaemon', _FakeDaemon)
    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, 'format_status', _fake_format_status)

    rc = run_gateway_command(['status'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'DAEMON: running' in out
    assert 'CHANNELS: all' in out
    assert len(daemon_status_calls) == 1
    assert format_status_calls == [(None, None, None)]


def test_gateway_disconnect_channel(monkeypatch) -> None:
    """`gateway disconnect <name>` calls _disconnect_gateway_connection."""
    calls: list[tuple] = []

    def _fake_disconnect(name: str, *, state_dir: str | None = None) -> int:
        calls.append((name, state_dir))
        return 0

    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, '_disconnect_gateway_connection', _fake_disconnect)
    rc = run_gateway_command(['disconnect', 'wechat'])
    assert rc == 0
    assert calls == [('wechat', None)]


def test_gateway_login_channel(monkeypatch) -> None:
    """`gateway login <name>` calls wechat_login."""
    calls: list[tuple] = []

    def _fake_login(name: str, *, state_dir: str | None = None) -> int:
        calls.append((name, state_dir))
        return 0

    from clawcodex_ext.cli.channels_cmd import commands as ch

    monkeypatch.setattr(ch, 'wechat_login', _fake_login)
    rc = run_gateway_command(['login', 'wechat'])
    assert rc == 0
    assert calls == [('wechat', None)]


def test_gateway_wizard_is_unknown(capsys) -> None:
    """`gateway wizard` is no longer valid — only `setup` runs the wizard."""
    rc = run_gateway_command(['wizard'])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'unknown gateway subcommand' in err
