"""Relevant session retrieval for Intent Forecast."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def rank_session_rows(
    rows: list[dict[str, Any]],
    *,
    cwd: str | Path,
    changed_files: list[str],
    recent_text: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Rank lightweight session rows by relevance to the active task."""

    cwd_text = str(cwd).replace("\\", "/").lower()
    changed_tokens = _tokens(" ".join(changed_files))
    recent_tokens = _tokens(recent_text)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        score = 0.0
        row_cwd = str(row.get("cwd") or "").replace("\\", "/").lower()
        if row_cwd and row_cwd == cwd_text:
            score += 4.0
        elif row_cwd and (row_cwd in cwd_text or cwd_text in row_cwd):
            score += 2.0

        summary_text = _summary_text(row.get("summary"))
        text = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("last_user_input") or ""),
                summary_text,
                _tail_text(row.get("transcript_tail")),
            ]
        )
        row_tokens = _tokens(text)
        if changed_tokens:
            score += 3.0 * _jaccard(changed_tokens, row_tokens)
        if recent_tokens:
            score += 2.0 * _jaccard(recent_tokens, row_tokens)

        files = []
        summary = row.get("summary")
        if isinstance(summary, dict) and isinstance(summary.get("files_touched"), list):
            files = [str(item) for item in summary["files_touched"]]
        if files and changed_files:
            overlap = _path_overlap(changed_files, files)
            score += 4.0 * overlap

        try:
            score += min(1.0, float(row.get("last_updated") or 0) / 10_000_000_000)
        except (TypeError, ValueError):
            pass
        row = dict(row)
        row["relevance_score"] = round(score, 4)
        ranked.append((score - index * 0.0001, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def _summary_text(summary: Any) -> str:
    if not isinstance(summary, dict):
        return ""
    parts: list[str] = []
    for key in ("title", "goals", "open_threads", "next_action_candidates", "files_touched", "commands_seen"):
        value = summary.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value[:10])
    return " ".join(parts)


def _tail_text(tail: Any) -> str:
    if not isinstance(tail, list):
        return ""
    return " ".join(str(item.get("content") or "") for item in tail if isinstance(item, dict))


def _tokens(text: str) -> set[str]:
    cleaned = text.replace("\\", "/").lower()
    out: set[str] = set()
    for raw in cleaned.replace("_", " ").replace("-", " ").replace("/", " ").split():
        token = raw.strip(".,:;()[]{}'\"")
        if len(token) >= 3:
            out.add(token)
    return out


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _path_overlap(left: list[str], right: list[str]) -> float:
    left_norm = {_path_key(path) for path in left}
    right_norm = {_path_key(path) for path in right}
    if not left_norm or not right_norm:
        return 0.0
    return len(left_norm & right_norm) / len(left_norm | right_norm)


def _path_key(path: str) -> str:
    parts = path.replace("\\", "/").lower().split("/")
    return "/".join(parts[-3:])
