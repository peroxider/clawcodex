"""Server-Sent Events helpers for OpenAI-compatible streams."""

from __future__ import annotations

import json
from typing import Any


def encode_sse(data: Any, *, event: str | None = None) -> str:
    """Encode one SSE frame."""

    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def encode_done() -> str:
    return encode_sse("[DONE]")


def chat_chunk(
    *,
    chunk_id: str,
    created: int,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    include_usage: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    if include_usage:
        payload["usage"] = usage
    return payload


def chat_usage_chunk(
    *,
    chunk_id: str,
    created: int,
    model: str,
    usage: dict[str, int],
) -> dict[str, Any]:
    """Build the final usage-only chunk requested by ``stream_options``."""

    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [],
        "usage": usage,
    }
