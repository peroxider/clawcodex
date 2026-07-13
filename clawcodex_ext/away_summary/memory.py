"""Session-level memory helpers for Away Summary.

Mirrors the optional broader-context injection used by the upstream
``src/services/awaySummary.ts`` (which calls ``getSessionMemoryContent()``).
The clawcodex equivalent reads the session-summary sidecar emitted by
:mod:`clawcodex_ext.session_intelligence` and projects it into a short,
human-readable block the recap prompt can prepend to its instructions.

The default behaviour is *off* — only flip on via
``AwaySummaryConfig.include_session_memory = True`` — so the auto recap
remains byte-identical to its prior behaviour unless the user opts in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clawcodex_ext.session_intelligence.index import load_summary


def get_session_memory_content(
    *,
    session_id: str | None = None,
    max_chars: int = 4000,
    sessions_dir: Path | None = None,
) -> str | None:
    """Return a short session-memory block for prompt injection, or None.

    Reads :func:`clawcodex_ext.session_intelligence.index.load_summary`
    which returns the ``summary.json`` sidecar produced by the lazy
    sidecar pipeline. The function is intentionally tolerant: any IO /
    parse / missing-file error yields ``None`` so the recap never crashes
    because the sidecar is unavailable.
    """
    if not session_id:
        return None
    try:
        data = load_summary(session_id, sessions_dir=sessions_dir)
    except Exception:
        return None
    if not data:
        return None
    return _format_memory(data, max_chars=max_chars)


def _format_memory(data: dict[str, Any], *, max_chars: int) -> str | None:
    """Project a session summary dict into a recap-friendly block."""
    lines: list[str] = []

    title = str(data.get("title") or "").strip()
    if title:
        lines.append(f"Title: {title}")

    cwd = str(data.get("cwd") or "").strip()
    if cwd:
        lines.append(f"Working directory: {cwd}")

    sections: list[tuple[str, list[str]]] = [
        ("Goals", list(data.get("goals") or [])),
        ("Completed", list(data.get("completed") or [])),
        ("Open threads", list(data.get("open_threads") or [])),
        ("Next candidates", list(data.get("next_action_candidates") or [])),
        ("User preferences", list(data.get("user_preferences") or [])),
    ]
    for label, items in sections:
        clean = [str(x).strip() for x in items if str(x or "").strip()]
        if not clean:
            continue
        lines.append(f"{label}:")
        # Tail-truncate each list so the recap stays short even when the
        # sidecar accumulated many entries across long sessions.
        for item in clean[-5:]:
            lines.append(f"- {item}")

    text = "\n".join(lines).strip()
    if not text:
        return None
    if len(text) > max_chars:
        return text[: max_chars].rstrip() + "…"
    return text