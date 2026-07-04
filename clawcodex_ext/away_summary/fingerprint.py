"""Conversation fingerprint helpers for Away Summary."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def conversation_fingerprint(conversation: Any) -> str:
    """Return a stable hash for user/assistant-visible conversation content."""

    messages = list(getattr(conversation, "messages", []) or [])
    payload: list[dict[str, Any]] = []
    for msg in messages:
        if is_away_summary_message(msg):
            continue
        if getattr(msg, "isVirtual", False):
            continue
        role = getattr(msg, "role", "")
        if role not in {"user", "assistant"}:
            continue
        payload.append(
            {
                "role": role,
                "content": _jsonable(getattr(msg, "content", "")),
                "uuid": getattr(msg, "uuid", None),
            }
        )
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def session_turn_count(conversation: Any) -> int:
    """Count completed user/assistant pairs."""

    users = 0
    assistants = 0
    for msg in getattr(conversation, "messages", []) or []:
        if is_away_summary_message(msg):
            continue
        role = getattr(msg, "role", "")
        if role == "user":
            users += 1
        elif role == "assistant":
            assistants += 1
    return min(users, assistants)


def last_away_summary_fingerprint(
    conversation: Any,
    *,
    trigger: str | None = None,
) -> str | None:
    for msg in reversed(list(getattr(conversation, "messages", []) or [])):
        if not is_away_summary_message(msg):
            continue
        meta = getattr(msg, "_away_summary_meta", None)
        if isinstance(meta, dict):
            if trigger is not None and meta.get("trigger") != trigger:
                continue
            value = meta.get("fingerprint")
            return str(value) if value else None
        content = _flatten_content(getattr(msg, "content", ""))
        if trigger is not None:
            marker = "trigger="
            if marker not in content:
                continue
            found = content.split(marker, 1)[1].split()[0].strip()
            if found != trigger:
                continue
        marker = "fingerprint="
        if marker in content:
            return content.split(marker, 1)[1].split()[0].strip()
    return None


def is_away_summary_message(msg: Any) -> bool:
    if getattr(msg, "role", "") != "system":
        return False
    if getattr(msg, "subtype", None) == "away_summary":
        return True
    return "[AWAY SUMMARY]" in _flatten_content(getattr(msg, "content", ""))


def _jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dict__"):
        return _jsonable(value.__dict__)
    return value


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(content)
