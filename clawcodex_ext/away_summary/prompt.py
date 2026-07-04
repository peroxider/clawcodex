"""Prompt construction for Away Summary."""

from __future__ import annotations

import json
from typing import Any

from clawcodex_ext.away_summary.fingerprint import is_away_summary_message


AWAY_SUMMARY_INSTRUCTIONS = """You are writing a short session recap for a user who stepped away from an interactive coding session.

Write a concise recap of the full session so far. Use 3-6 bullets maximum.
Write the recap in the dominant language of the recent conversation.
Focus on:
- what the user asked for,
- important decisions and current state,
- files or commands that matter,
- the next useful action when the user returns.

Do not include hidden reasoning. Do not mention that you are an AI. Keep it brief."""


def build_summary_messages(
    conversation: Any,
    *,
    max_input_tokens: int,
) -> list[dict[str, str]]:
    transcript = _serialize_transcript(conversation)
    transcript = _truncate_transcript(transcript, max_input_tokens=max_input_tokens)
    return [
        {
            "role": "user",
            "content": (
                f"{AWAY_SUMMARY_INSTRUCTIONS}\n\n"
                "Session transcript:\n"
                f"{transcript}\n\n"
                "Return only the recap."
            ),
        }
    ]


def _serialize_transcript(conversation: Any) -> str:
    lines: list[str] = []
    for msg in getattr(conversation, "messages", []) or []:
        if is_away_summary_message(msg):
            continue
        role = getattr(msg, "role", "")
        if role not in {"user", "assistant"}:
            continue
        text = _content_to_text(getattr(msg, "content", ""))
        if not text.strip():
            continue
        lines.append(f"{role}: {text.strip()}")
    return "\n\n".join(lines)


def _truncate_transcript(transcript: str, *, max_input_tokens: int) -> str:
    if _estimate_tokens(transcript) <= max_input_tokens:
        return transcript
    # Approximate 4 chars/token, keeping a small head and a larger recent tail.
    budget_chars = max_input_tokens * 4
    head_chars = min(4_000, max(1_000, budget_chars // 5))
    tail_chars = max(1_000, budget_chars - head_chars - 200)
    return (
        transcript[:head_chars].rstrip()
        + "\n\n[... earlier middle of session omitted for recap budget ...]\n\n"
        + transcript[-tail_chars:].lstrip()
    )


def _estimate_tokens(text: str) -> int:
    try:
        from clawcodex_ext.utils.token_estimation import count_tokens

        return int(count_tokens(text))
    except Exception:
        return max(1, len(text) // 4)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
                continue
            kind = getattr(item, "type", None)
            if kind == "tool_use":
                name = getattr(item, "name", "")
                raw_input = getattr(item, "input", {})
                parts.append(f"[tool_use {name} {json.dumps(raw_input, default=str)}]")
                continue
            if isinstance(item, dict):
                if item.get("type") in (None, "text"):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                elif item.get("type") == "tool_use":
                    parts.append(f"[tool_use {item.get('name') or ''}]")
                elif item.get("type") == "tool_result":
                    parts.append(f"[tool_result {item.get('content') or ''}]")
                continue
            parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(content)
