from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, MutableMapping

from dotenv import dotenv_values


MEMORY_ENV_FILE_NAME = "memory.env"
PASSIVE_MEMORY_ENV_PREFIX = "CLAWCODEX_PASSIVE_MEMORY"


def memory_state_dir(
    environ: Mapping[str, str] | None = None,
    state_dir: str | Path | None = None,
) -> Path:
    source = os.environ if environ is None else environ
    configured = state_dir or source.get("CLAWCODEX_MEMORY_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    config_root = Path(
        source.get("CLAWCODEX_CONFIG_DIR", str(Path.home() / ".clawcodex"))
    ).expanduser()
    return (config_root / "memory").resolve()


def default_memory_env_path(
    environ: Mapping[str, str] | None = None,
    state_dir: str | Path | None = None,
) -> Path:
    return memory_state_dir(environ, state_dir) / MEMORY_ENV_FILE_NAME


def read_memory_env_file(path: Path) -> dict[str, str]:
    return {
        str(name): str(value)
        for name, value in dotenv_values(path).items()
        if name and value is not None
    }


def load_memory_server_environment(
    env_file: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
    state_dir: str | Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    target = os.environ if environ is None else environ
    project_env = Path(cwd or Path.cwd()) / ".env"
    project_values = read_memory_env_file(project_env) if project_env.is_file() else {}
    effective = {**project_values, **target}
    configured_file = (
        env_file
        or target.get("CLAWCODEX_MEMORY_ENV_FILE")
        or project_values.get("CLAWCODEX_MEMORY_ENV_FILE")
    )
    default_file = default_memory_env_path(effective, state_dir)

    values = dict(project_values)
    if default_file.is_file():
        values.update(read_memory_env_file(default_file))
    if configured_file:
        configured_path = Path(configured_file).expanduser()
        if not configured_path.is_file():
            raise FileNotFoundError(f"Memory env file not found: {configured_path}")
        if configured_path.resolve() != default_file.resolve():
            values.update(read_memory_env_file(configured_path))

    for name, value in values.items():
        target.setdefault(name, value)


def load_passive_memory_environment(
    *,
    cwd: str | Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Load CLAWCODEX_PASSIVE_MEMORY* vars into *environ* (default os.environ).

    Lookup order (later sources do NOT override earlier ones — setdefault):
      1. Project ``.env`` in *cwd* (or CWD)
      2. ``memory.env`` in the memory state dir (~/.clawcodex/memory/memory.env)
      3. Explicit file pointed to by CLAWCODEX_MEMORY_ENV_FILE

    Returns the path of the primary env file used, or None if nothing found.
    """
    target = os.environ if environ is None else environ

    # 1. Project .env (same directory the agent is launched from)
    project_env = Path(cwd or Path.cwd()) / ".env"
    if project_env.is_file():
        for name, value in read_memory_env_file(project_env).items():
            if name == PASSIVE_MEMORY_ENV_PREFIX or name.startswith(
                f"{PASSIVE_MEMORY_ENV_PREFIX}_"
            ):
                target.setdefault(name, value)

    # 2. Default memory.env in state dir
    configured_file = target.get("CLAWCODEX_MEMORY_ENV_FILE")
    env_path = (
        Path(configured_file).expanduser() if configured_file else default_memory_env_path(target)
    )
    if not env_path.is_file():
        # Even if memory.env doesn't exist, project .env may have loaded vars.
        return project_env if project_env.is_file() else None

    for name, value in read_memory_env_file(env_path).items():
        if name == PASSIVE_MEMORY_ENV_PREFIX or name.startswith(f"{PASSIVE_MEMORY_ENV_PREFIX}_"):
            target.setdefault(name, value)
    return env_path


__all__ = [
    "MEMORY_ENV_FILE_NAME",
    "default_memory_env_path",
    "load_memory_server_environment",
    "load_passive_memory_environment",
    "memory_state_dir",
    "read_memory_env_file",
]
