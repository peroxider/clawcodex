"""Cost-state restore orchestrator.

Mirrors TS ``cost-tracker.ts:149`` (``restoreCostStateForSession``). Reads
the persisted cost snapshot for a given session ID and dispatches
``set_cost_state_for_restore`` into the bootstrap singleton so the
``/resume`` path picks up where the last session left off, rather than
silently starting from zero.

F-49 P5-C: primary source is the ``session.json`` snapshot (fast path).
When ``session.json`` does not exist (orchestrator/cron sessions that
only write JSONL), falls back to scanning the last ``cost_block`` entry
in ``transcript.jsonl`` via ``tail -1``-style read.

The TS file ``cost-tracker.ts`` does two things: defines the
``CostTracker`` class (which Python's port has consolidated onto the
bootstrap singleton) and the restore orchestrator. The orchestrator is
the only piece that needs its own file in Python — pricing is at
``src/services/pricing.py`` and accounting is at
``src/bootstrap/state.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.bootstrap.state import (
    ModelUsage,
    SessionId,
    set_cost_state_for_restore,
)


def _sessions_dir() -> Path:
    """Persistence directory — extracted so tests can monkeypatch."""
    return Path.home() / ".clawcodex" / "sessions"


def _restore_from_cost_block(cost_block: dict[str, Any]) -> None:
    """Dispatch a ``cost_block`` dict into the bootstrap singleton.

    Shared by both the ``session.json`` path and the ``transcript.jsonl``
    fallback (P5-C).  Extracted so the two code paths call the same
    restore logic.
    """
    model_usage_raw: dict[str, Any] = cost_block.get("model_usage", {}) or {}
    model_usage: dict[str, ModelUsage] = {}
    for model, entry in model_usage_raw.items():
        if not isinstance(entry, dict):
            continue
        model_usage[model] = ModelUsage(
            input_tokens=int(entry.get("input_tokens", 0)),
            output_tokens=int(entry.get("output_tokens", 0)),
            cache_creation_input_tokens=int(entry.get("cache_creation_input_tokens", 0)),
            cache_read_input_tokens=int(entry.get("cache_read_input_tokens", 0)),
            cost_usd=float(entry.get("cost_usd", 0.0)),
        )

    set_cost_state_for_restore(
        total_cost_usd=float(cost_block.get("total_cost_usd", 0.0)),
        total_api_duration=int(cost_block.get("total_api_duration", 0)),
        total_api_duration_without_retries=int(
            cost_block.get("total_api_duration_without_retries", 0)
        ),
        total_tool_duration=int(cost_block.get("total_tool_duration", 0)),
        total_lines_added=int(cost_block.get("total_lines_added", 0)),
        total_lines_removed=int(cost_block.get("total_lines_removed", 0)),
        last_duration=cost_block.get("last_duration"),
        model_usage=model_usage if model_usage else None,
    )


def _restore_from_jsonl_tail(session_id: str) -> bool:
    """F-49 P5-C: read the last ``cost_block`` entry from ``transcript.jsonl``.

    Scans ``~/.clawcodex/sessions/<sid>/transcript.jsonl`` for the last
    line whose ``"type"`` equals ``"cost_block"``.  This is the fallback
    when ``session.json`` does not exist (orchestrator / cron sessions).

    Returns True if a cost block was found and applied, False otherwise.
    """
    transcript_path = _sessions_dir() / session_id / "transcript.jsonl"
    if not transcript_path.exists():
        return False

    last_cost_block: dict[str, Any] | None = None
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("type") == "cost_block":
                    cost = entry.get("cost")
                    if isinstance(cost, dict):
                        last_cost_block = cost
    except OSError:
        return False

    if last_cost_block is None:
        return False

    _restore_from_cost_block(last_cost_block)
    return True


def restore_cost_state_for_session(session_id: SessionId | str) -> bool:
    """Restore cost accumulators from the persisted snapshot for
    ``session_id``.

    Returns True if the snapshot was found and applied, False otherwise.

    Mirrors TS ``restoreCostStateForSession`` semantics: the gate is the
    **persisted file's session_id**, not the bootstrap singleton's
    runtime session_id. This means the function works regardless of
    whether ``switch_session(sid)`` was called first — the resume path
    can call restore-then-switch or switch-then-restore.

    F-49 P5-C: primary source is ``session.json`` (same place
    ``Session.save`` writes).  When ``session.json`` does not exist,
    falls back to scanning ``transcript.jsonl`` for the last
    ``cost_block`` entry.
    """
    target = str(session_id)
    session_file = _sessions_dir() / target / "session.json"
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text())
        except (OSError, json.JSONDecodeError):
            return False

        if not isinstance(data, dict):
            return False

        # Gate on the *persisted* session_id matching the target — mirrors
        # the TS pattern. Refuses to restore from a file whose session_id
        # header doesn't agree with the filename (defends against a renamed
        # or hand-edited file).
        persisted_sid = data.get("session_id")
        if persisted_sid != target:
            return False

        # Extract cost fields with defaults — tolerate snapshots that
        # don't yet persist them.
        cost_block: dict[str, Any] = data.get("cost", {}) if isinstance(data, dict) else {}
        _restore_from_cost_block(cost_block)
        return True

    # F-49 P5-C: fallback to transcript.jsonl when no .json snapshot exists.
    return _restore_from_jsonl_tail(target)


__all__ = ["restore_cost_state_for_session"]
