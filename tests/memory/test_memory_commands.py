from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawcodex_ext.cli.memory_cmd.commands import run_memory_command


@contextmanager
def _command_mocks(tmp_path: Path):
    paths = MagicMock()
    paths.state_dir = tmp_path / "state"
    with (
        patch("clawcodex_ext.latent_memory.server.daemon.load_memory_environment") as load_env,
        patch(
            "clawcodex_ext.latent_memory.server.daemon.MemoryServerPaths.for_state_dir",
            return_value=paths,
        ) as build_paths,
        patch("clawcodex_ext.latent_memory.server.daemon.MemoryServerDaemon") as daemon_class,
    ):
        yield paths, load_env, build_paths, daemon_class


def test_enable_installs_project_integration_and_starts_daemon(tmp_path: Path) -> None:
    integration_result = (tmp_path / ".mcp.json", tmp_path / ".env")
    with (
        _command_mocks(tmp_path) as (paths, load_env, build_paths, daemon_class),
        patch(
            "clawcodex_ext.latent_memory.project_integration.enable_project_integration",
            return_value=integration_result,
        ) as enable_integration,
    ):
        daemon_class.return_value.start.return_value = 0
        result = run_memory_command(["enable", "--timeout", "3"])

    assert result == 0
    enable_integration.assert_called_once_with()
    daemon_class.return_value.start.assert_called_once_with(env_file=None, timeout=3.0)


def test_disable_stops_daemon_and_removes_project_integration(tmp_path: Path) -> None:
    integration_result = (tmp_path / ".mcp.json", tmp_path / ".env")
    with (
        _command_mocks(tmp_path) as (paths, load_env, build_paths, daemon_class),
        patch(
            "clawcodex_ext.latent_memory.project_integration.disable_project_integration",
            return_value=integration_result,
        ) as disable_integration,
    ):
        daemon_class.return_value.stop.return_value = 0
        result = run_memory_command(["disable", "--timeout", "4"])

    assert result == 0
    daemon_class.return_value.stop.assert_called_once_with(timeout=4.0)
    disable_integration.assert_called_once_with()


def test_serve_installs_then_removes_project_integration(tmp_path: Path) -> None:
    integration_result = (tmp_path / ".mcp.json", tmp_path / ".env")
    with (
        _command_mocks(tmp_path) as (paths, load_env, build_paths, daemon_class),
        patch(
            "clawcodex_ext.latent_memory.project_integration.enable_project_integration",
            return_value=integration_result,
        ) as enable_integration,
        patch(
            "clawcodex_ext.latent_memory.server.daemon.serve_foreground", return_value=7
        ) as serve,
        patch(
            "clawcodex_ext.latent_memory.project_integration.disable_project_integration",
            return_value=integration_result,
        ) as disable_integration,
    ):
        result = run_memory_command(["serve"])

    assert result == 7
    enable_integration.assert_called_once_with()
    serve.assert_called_once_with(Path(paths.state_dir))
    disable_integration.assert_called_once_with()


def test_serve_removes_project_integration_when_foreground_server_raises(tmp_path: Path) -> None:
    integration_result = (tmp_path / ".mcp.json", tmp_path / ".env")
    with (
        _command_mocks(tmp_path),
        patch(
            "clawcodex_ext.latent_memory.project_integration.enable_project_integration",
            return_value=integration_result,
        ),
        patch(
            "clawcodex_ext.latent_memory.server.daemon.serve_foreground",
            side_effect=KeyboardInterrupt,
        ),
        patch(
            "clawcodex_ext.latent_memory.project_integration.disable_project_integration",
            return_value=integration_result,
        ) as disable_integration,
    ):
        with pytest.raises(KeyboardInterrupt):
            run_memory_command(["serve"])

    disable_integration.assert_called_once_with()


def test_serve_disables_passive_memory_when_mcp_cleanup_fails(tmp_path: Path) -> None:
    integration_result = (tmp_path / ".mcp.json", tmp_path / ".env")
    with (
        _command_mocks(tmp_path),
        patch(
            "clawcodex_ext.latent_memory.project_integration.enable_project_integration",
            return_value=integration_result,
        ),
        patch("clawcodex_ext.latent_memory.server.daemon.serve_foreground", return_value=0),
        patch(
            "clawcodex_ext.latent_memory.project_integration.disable_project_integration",
            side_effect=OSError("cannot update .mcp.json"),
        ),
        patch(
            "clawcodex_ext.latent_memory.project_integration.set_passive_memory_enabled",
            return_value=tmp_path / ".env",
        ) as set_passive_memory,
    ):
        result = run_memory_command(["serve"])

    assert result == 0
    set_passive_memory.assert_called_once_with(False)


@pytest.mark.parametrize("legacy_command", ["start", "stop"])
def test_legacy_start_and_stop_commands_are_not_registered(legacy_command: str) -> None:
    with pytest.raises(SystemExit):
        run_memory_command([legacy_command])
