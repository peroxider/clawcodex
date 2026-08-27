from __future__ import annotations

import json
from pathlib import Path

import pytest

from clawcodex_ext.latent_memory.project_integration import (
    disable_project_integration,
    enable_project_integration,
    memory_mcp_config,
    set_passive_memory_enabled,
)


@pytest.fixture(autouse=True)
def _restore_passive_memory_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAWCODEX_PASSIVE_MEMORY", raising=False)


def _mcp_data(project: Path) -> dict:
    return json.loads((project / ".mcp.json").read_text(encoding="utf-8"))


def test_enable_is_idempotent_and_preserves_project_settings(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OTHER=value\nCLAWCODEX_PASSIVE_MEMORY=0\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "echo"}}, "custom": True}),
        encoding="utf-8",
    )

    enable_project_integration(tmp_path)
    enable_project_integration(tmp_path)

    data = _mcp_data(tmp_path)
    assert data["custom"] is True
    assert data["mcpServers"]["other"] == {"command": "echo"}
    assert data["mcpServers"]["latent-memory"] == memory_mcp_config()
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OTHER=value" in env_text
    assert env_text.count("CLAWCODEX_PASSIVE_MEMORY=1") == 1


def test_enable_refuses_to_overwrite_conflicting_memory_server(tmp_path: Path) -> None:
    original = {"mcpServers": {"latent-memory": {"command": "custom-memory"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError, match="different configuration"):
        enable_project_integration(tmp_path)

    assert _mcp_data(tmp_path) == original
    assert not (tmp_path / ".env").exists()


def test_enable_updates_managed_mcp_target_when_port_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enable_project_integration(tmp_path)
    monkeypatch.setenv("MEMORY_SERVER_PORT", "9999")

    enable_project_integration(tmp_path)

    managed = _mcp_data(tmp_path)["mcpServers"]["latent-memory"]
    assert managed["env"]["MEM0_HOST"] == "http://127.0.0.1:9999"


def test_default_project_is_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    enable_project_integration()
    assert "latent-memory" in _mcp_data(tmp_path)["mcpServers"]

    disable_project_integration()
    assert "latent-memory" not in _mcp_data(tmp_path)["mcpServers"]


def test_disable_removes_only_managed_memory_configuration(tmp_path: Path) -> None:
    enable_project_integration(tmp_path)
    data = _mcp_data(tmp_path)
    data["mcpServers"]["other"] = {"command": "echo"}
    (tmp_path / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")

    disable_project_integration(tmp_path)

    assert _mcp_data(tmp_path)["mcpServers"] == {"other": {"command": "echo"}}
    assert "CLAWCODEX_PASSIVE_MEMORY=0" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_disable_refuses_to_remove_unmanaged_memory_server(tmp_path: Path) -> None:
    original = {"mcpServers": {"latent-memory": {"command": "custom-memory"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(ValueError, match="not managed by latent memory"):
        disable_project_integration(tmp_path)

    assert _mcp_data(tmp_path) == original


def test_passive_switch_can_be_disabled_without_removing_mcp(tmp_path: Path) -> None:
    enable_project_integration(tmp_path)

    env_path = set_passive_memory_enabled(False, tmp_path)

    assert "CLAWCODEX_PASSIVE_MEMORY=0" in env_path.read_text(encoding="utf-8")
    assert "latent-memory" in _mcp_data(tmp_path)["mcpServers"]
