"""Feedback persistence for Intent Forecast."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from clawcodex_ext.intent_forecast.messages import ForecastSuggestion


def feedback_path(base_dir: Path | None = None) -> Path:
    root = base_dir or (Path.home() / ".clawcodex")
    return root / "intent_forecast" / "feedback.jsonl"


def record_feedback(
    event: str,
    *,
    suggestion: ForecastSuggestion | None = None,
    cwd: str | Path | None = None,
    fingerprint: str = "",
    features: dict[str, Any] | None = None,
    base_dir: Path | None = None,
) -> None:
    path = feedback_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "event": event,
        "cwd": str(cwd or ""),
        "fingerprint": fingerprint,
        "features": features or {},
        "created_at": time.time(),
    }
    if suggestion is not None:
        payload.update(
            {
                "suggestion_id": suggestion.id,
                "title": suggestion.title,
                "prompt": suggestion.prompt,
                "confidence": suggestion.confidence,
            }
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_recent_feedback(*, limit: int = 50, base_dir: Path | None = None) -> list[dict[str, Any]]:
    path = feedback_path(base_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    except OSError:
        return []
    return rows


def feedback_weight(
    suggestion_title: str,
    *,
    cwd: str | Path | None = None,
    fingerprint: str = "",
    base_dir: Path | None = None,
) -> float:
    """Return a small ranking adjustment from recent feedback."""

    title = suggestion_title.strip().lower()
    if not title:
        return 0.0
    weight = 0.0
    cwd_text = str(cwd or "")
    for row in read_recent_feedback(limit=200, base_dir=base_dir):
        row_title = str(row.get("title") or "").strip().lower()
        if not row_title:
            continue
        same_cwd = not cwd_text or str(row.get("cwd") or "") == cwd_text
        similar = title in row_title or row_title in title
        if not (same_cwd and similar):
            continue
        event = str(row.get("event") or "")
        if event == "accepted":
            weight += 0.06
        elif event in {"dismissed", "rejected"}:
            weight -= 0.08
        if fingerprint and row.get("fingerprint") == fingerprint and event == "dismissed":
            weight -= 0.12
    return max(-0.25, min(0.25, weight))
