from __future__ import annotations

import logging
from typing import Any

from .config import PassiveMemoryConfig
from .scope import build_memory_ids


logger = logging.getLogger(__name__)

MEMORY_TOOLS_WITH_USER_SCOPE = frozenset(
    {
        "memory_add_text",
        "memory_add_messages",
        "memory_search",
        "memory_list",
        "memory_delete_all",
        "memory_crystallize",
        "memory_crystallizer_composition",
    }
)


def inject_project_user_id(
    args: dict[str, Any],
    context: Any,
    *,
    server_name: str,
    tool_name: str,
    accepts_user_id: bool | None = None,
    config: PassiveMemoryConfig | None = None,
) -> dict[str, Any]:
    """Apply passive recall's project user scope to an active MCP call."""
    if "user_id" in args:
        return args
    if accepts_user_id is None:
        accepts_user_id = tool_name in MEMORY_TOOLS_WITH_USER_SCOPE
    if not accepts_user_id:
        return args
    try:
        cfg = config or PassiveMemoryConfig.from_env()
    except Exception:
        return args
    if not cfg.enabled or cfg.server_name != server_name:
        return args
    try:
        user_id = build_memory_ids(cfg, context).user_id
    except Exception:
        return args
    scoped = dict(args)
    scoped["user_id"] = user_id
    logger.debug(
        "MCP %s/%s: injected passive-memory project user_id=%s",
        server_name,
        tool_name,
        user_id,
    )
    return scoped


__all__ = ["MEMORY_TOOLS_WITH_USER_SCOPE", "inject_project_user_id"]
