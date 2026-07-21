"""Session-scoped tool state for cross-invocation secrets (bridge P0).

Persists configure-tool outputs (e.g. ``llm_api_key``) so downstream
``cli_main`` wrapper subprocesses can inject them via stdin JSON or env
without relying on in-process ``MemoryConfig`` (which does not survive
separate wrapper invocations).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TOOL_STATE_FILENAME = "tool-state.json"

_CONFIGURE_TOOL_SUBSTRINGS = (
    "set-llm-api-key",
    "memoryconfig-set-llm-api-key",
)

_CLI_SECRET_TOOL_SUBSTRINGS = (
    "execute-application",
)


def resolve_sessions_dir() -> Path:
    """Match ``extensions.agent.session_persist._resolve_sessions_dir``."""
    override = str(os.environ.get("CLAWCODEX_SESSIONS_DIR", "")).strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".clawcodex" / "sessions"


def tool_state_path(session_id: str) -> Path:
    return resolve_sessions_dir() / session_id / TOOL_STATE_FILENAME


def load_tool_state(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    path = tool_state_path(session_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_tool_state(session_id: str | None, state: dict[str, Any]) -> None:
    if not session_id:
        return
    path = tool_state_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def set_session_secret(session_id: str | None, key: str, value: str | None) -> None:
    if not session_id or not value:
        return
    state = load_tool_state(session_id)
    secrets = state.get("secrets")
    if not isinstance(secrets, dict):
        secrets = {}
    secrets[key] = value
    state["secrets"] = secrets
    save_tool_state(session_id, state)


def get_session_secrets(session_id: str | None) -> dict[str, str]:
    state = load_tool_state(session_id)
    secrets = state.get("secrets", {})
    if not isinstance(secrets, dict):
        return {}
    return {str(k): str(v) for k, v in secrets.items() if v is not None and str(v)}


def is_configure_tool(tool_name: str) -> bool:
    name = tool_name.lower()
    return any(substr in name for substr in _CONFIGURE_TOOL_SUBSTRINGS)


def is_cli_secret_consumer(tool_name: str) -> bool:
    name = tool_name.lower()
    return any(substr in name for substr in _CLI_SECRET_TOOL_SUBSTRINGS)


def enrich_tool_input(
    tool_name: str,
    params: dict[str, Any],
    session_id: str | None,
) -> dict[str, Any]:
    """Inject session secrets into cli_main tool calls before wrapper dispatch."""
    if not is_cli_secret_consumer(tool_name) or not session_id:
        return dict(params)

    secrets = get_session_secrets(session_id)
    llm_key = secrets.get("llm_api_key")
    if not llm_key:
        return dict(params)

    enriched = dict(params)
    stdin_config = dict(enriched.get("__stdin_config") or {})
    stdin_config.setdefault("llm_api_key", llm_key)
    enriched["__stdin_config"] = stdin_config

    env = dict(enriched.get("__env") or {})
    env.setdefault("LLM_API_KEY", llm_key)
    env.setdefault("DEEPSEEK_API_KEY", llm_key)
    enriched["__env"] = env
    if llm_key and "__interactive_inputs" not in enriched:
        enriched["__interactive_inputs"] = [llm_key]
    return enriched


def persist_configure_secrets(
    tool_name: str,
    params: dict[str, Any],
    session_id: str | None,
) -> None:
    """After a successful configure tool call, persist secrets for the session."""
    if not is_configure_tool(tool_name) or not session_id:
        return
    api_key = params.get("api_key")
    if api_key:
        set_session_secret(session_id, "llm_api_key", str(api_key))
