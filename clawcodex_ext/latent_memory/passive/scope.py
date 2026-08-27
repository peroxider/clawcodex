from __future__ import annotations

import getpass
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PassiveMemoryConfig


_COMPONENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class MemoryIds:
    user_id: str
    agent_id: str
    run_id: str
    project_key: str

    def search_args(self, scope: str) -> dict[str, str]:
        args = {"user_id": self.user_id}
        if scope == "agent":
            args["agent_id"] = self.agent_id
        elif scope == "run":
            args["run_id"] = self.run_id
        return args

    def write_args(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
        }


def build_memory_ids(
    config: PassiveMemoryConfig,
    tool_context: Any,
    *,
    fallback_session_id: str | None = None,
) -> MemoryIds:
    workspace = Path(
        getattr(tool_context, "workspace_root", None)
        or getattr(tool_context, "cwd", None)
        or Path.cwd()
    ).resolve()
    project_key = build_project_key(workspace)
    human_id = _component(config.human_id or getpass.getuser(), "user")
    user_id = f"ccx:{human_id}:project:{project_key}"

    raw_session_id = str(
        getattr(tool_context, "session_id", None) or fallback_session_id or ""
    ).strip()
    if not raw_session_id:
        raise ValueError("Passive memory requires a stable ClawCodex session id")
    run_id = raw_session_id if raw_session_id.startswith("ccxrun:") else f"ccxrun:{raw_session_id}"

    agent_id = config.agent_id
    if not agent_id.startswith("ccx:"):
        agent_id = f"ccx:{_component(agent_id, 'primary')}"
    return MemoryIds(
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        project_key=project_key,
    )


def build_project_key(workspace: Path) -> str:
    git_root = _git_value(workspace, "rev-parse", "--show-toplevel")
    root = Path(git_root).resolve() if git_root else workspace.resolve()
    remote = _git_value(root, "config", "--get", "remote.origin.url")
    canonical_project = remote or str(root)
    project_hash = hashlib.sha256(canonical_project.encode("utf-8")).hexdigest()[:8]
    repo_name = _component(root.name, "project")
    return f"{repo_name}-{project_hash}"


def _git_value(cwd: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip() if completed.returncode == 0 else ""
    return value or None


def _component(value: str, fallback: str) -> str:
    normalized = _COMPONENT_RE.sub("-", value.strip()).strip("-._").lower()
    return normalized or fallback


__all__ = ["MemoryIds", "build_memory_ids", "build_project_key"]
