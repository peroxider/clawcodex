"""Persisted message helpers for Away Summary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clawcodex_ext.types.messages import SystemMessage


def create_away_summary_message(
    summary: str,
    *,
    trigger: str,
    fingerprint: str,
    message_count: int,
    model: str | None = None,
) -> SystemMessage:
    text = (
        "[AWAY SUMMARY]\n"
        f"trigger={trigger} fingerprint={fingerprint} model={model or ''}\n\n"
        f"{summary.strip()}"
    )
    msg = SystemMessage(
        content=text,
        timestamp=datetime.now().isoformat(),
        subtype="away_summary",
        level="info",
        isMeta=False,
    )
    msg._away_summary_meta = {
        "trigger": trigger,
        "fingerprint": fingerprint,
        "message_count": message_count,
        "model": model,
        "created_at": msg.timestamp,
    }
    return msg


def format_away_summary_for_display(message_or_text: Any) -> str:
    if isinstance(message_or_text, str):
        text = message_or_text
    else:
        text = str(getattr(message_or_text, "content", "") or "")
    if text.startswith("[AWAY SUMMARY]"):
        parts = text.split("\n\n", 1)
        text = parts[1] if len(parts) > 1 else text
    return "Recapitulate\n" + text.strip()
