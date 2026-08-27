"""Project-local activation for the bundled latent-memory integration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from clawcodex_ext.services.mcp.config import add_mcp_config


MEMORY_MCP_SERVER_NAME = "latent-memory"
PASSIVE_MEMORY_ENV_NAME = "CLAWCODEX_PASSIVE_MEMORY"
MANAGED_MCP_ENV_NAME = "CLAWCODEX_LATENT_MEMORY_MANAGED_MCP"


def memory_mcp_config() -> dict[str, Any]:
    """Return the project MCP entry managed by ``memory enable``."""
    host = os.getenv("MEMORY_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "localhost"}:
        host = "127.0.0.1"
    port = os.getenv("MEMORY_SERVER_PORT", "8888").strip() or "8888"
    return {
        "command": "clawcodex-dev",
        "args": ["memory", "mcp", "--add-early-return-seconds", "0"],
        "env": {
            "MEM0_HOST": f"http://{host}:{port}",
            "MEMORY_ADD_RETRY_MAX_RETRIES": "3",
            "MEMORY_ADD_RETRY_BACKOFF_BASE_SECONDS": "10",
            MANAGED_MCP_ENV_NAME: "1",
        },
    }


def enable_project_integration(project_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Enable passive and active memory for the current project.

    The generated ``.mcp.json`` and updated ``.env`` are project-local and
    gitignored. Existing unrelated settings are preserved. A conflicting
    ``latent-memory`` entry is never overwritten silently.
    """
    project = _project_dir(project_dir)
    mcp_path = project / ".mcp.json"
    env_path = project / ".env"
    existing = _read_project_mcp(mcp_path)
    servers = _mcp_servers(existing, mcp_path)
    expected = memory_mcp_config()
    configured = servers.get(MEMORY_MCP_SERVER_NAME)
    if configured is not None and not _is_managed_mcp_config(configured):
        raise ValueError(
            f"MCP server {MEMORY_MCP_SERVER_NAME!r} already exists in {mcp_path} "
            "with a different configuration"
        )
    if configured is None:
        if project != Path.cwd().resolve():
            _write_project_mcp(mcp_path, existing, expected)
        else:
            add_mcp_config(MEMORY_MCP_SERVER_NAME, expected, "project")
    elif configured != expected:
        servers[MEMORY_MCP_SERVER_NAME] = expected
        _write_json_atomic(mcp_path, existing)
    set_passive_memory_enabled(True, project)
    return mcp_path, env_path


def disable_project_integration(project_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Disable project memory without touching unrelated MCP or env settings."""
    project = _project_dir(project_dir)
    mcp_path = project / ".mcp.json"
    env_path = project / ".env"
    if mcp_path.is_file():
        existing = _read_project_mcp(mcp_path)
        servers = _mcp_servers(existing, mcp_path)
        configured = servers.get(MEMORY_MCP_SERVER_NAME)
        if configured is not None and not _is_managed_mcp_config(configured):
            raise ValueError(
                f"MCP server {MEMORY_MCP_SERVER_NAME!r} in {mcp_path} is not managed by "
                "latent memory; refusing to remove it"
            )
        if configured is not None:
            del servers[MEMORY_MCP_SERVER_NAME]
            _write_json_atomic(mcp_path, existing)
    set_passive_memory_enabled(False, project)
    return mcp_path, env_path


def set_passive_memory_enabled(
    enabled: bool,
    project_dir: str | Path | None = None,
) -> Path:
    """Persist only the project passive-memory switch."""
    project = _project_dir(project_dir)
    env_path = project / ".env"
    value = "1" if enabled else "0"
    _set_env_value(env_path, PASSIVE_MEMORY_ENV_NAME, value)
    os.environ[PASSIVE_MEMORY_ENV_NAME] = value
    return env_path


def _project_dir(project_dir: str | Path | None) -> Path:
    return Path(project_dir or Path.cwd()).expanduser().resolve()


def _read_project_mcp(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read project MCP config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Project MCP config {path} is not a JSON object")
    return data


def _mcp_servers(data: dict[str, Any], path: Path) -> dict[str, Any]:
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"mcpServers in {path} is not a JSON object")
    return servers


def _is_managed_mcp_config(config: Any) -> bool:
    if not isinstance(config, dict):
        return False
    env = config.get("env")
    return isinstance(env, dict) and env.get(MANAGED_MCP_ENV_NAME) == "1"


def _write_project_mcp(
    path: Path,
    data: dict[str, Any],
    config: dict[str, Any],
) -> None:
    servers = _mcp_servers(data, path)
    servers[MEMORY_MCP_SERVER_NAME] = config
    _write_json_atomic(path, data)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _set_env_value(path: Path, name: str, value: str) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    newline = "\r\n" if "\r\n" in text else "\n"
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=.*$")
    output: list[str] = []
    replaced = False
    for line in text.splitlines():
        if pattern.match(line):
            if not replaced:
                output.append(f"{name}={value}")
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(f"{name}={value}")
    rendered = newline.join(output) + newline
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        tmp_path.write_text(rendered, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "MEMORY_MCP_SERVER_NAME",
    "disable_project_integration",
    "enable_project_integration",
    "memory_mcp_config",
    "set_passive_memory_enabled",
]
