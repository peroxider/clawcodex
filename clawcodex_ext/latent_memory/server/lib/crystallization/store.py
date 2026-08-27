"""State and audit persistence for semantic crystallization."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("memory-server.crystallizer")


@dataclass
class CrystallizationState:
    """Crystallization state persisted to a JSON file."""

    last_run: dict[str, str] = field(default_factory=dict)
    last_check: dict[str, float] = field(default_factory=dict)
    last_check_passed: dict[str, bool] = field(default_factory=dict)
    last_failed_attempt: dict[str, float] = field(default_factory=dict)
    pending_ids: dict[str, list[str]] = field(default_factory=dict)
    fact_attempts: dict[str, int] = field(default_factory=dict)
    total_created: int = 0
    total_absorbed: int = 0
    total_failed: int = 0
    total_rejected: int = 0
    total_evicted: int = 0
    running: bool = False

    @property
    def total_operations(self) -> int:
        return self.total_created + self.total_absorbed


def _load_state(path: str) -> CrystallizationState:
    """Load the state from a JSON file. Returns the default state if the file is missing or corrupted."""
    p = Path(path)
    if not p.exists():
        return CrystallizationState()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        state = CrystallizationState(
            last_run=data.get("last_run", {}),
            last_check=data.get("last_check", {}),
            last_check_passed=data.get("last_check_passed", {}),
            last_failed_attempt=data.get("last_failed_attempt", {}),
            pending_ids=data.get("pending_ids", {}),
            fact_attempts=data.get("fact_attempts", {}),
            total_created=data.get("total_created", data.get("total_crystallized", 0)),
            total_absorbed=data.get("total_absorbed", 0),
            total_failed=data.get("total_failed", 0),
            total_rejected=data.get("total_rejected", 0),
            total_evicted=data.get("total_evicted", 0),
            running=False,
        )
        if data.get("running"):
            logger.warning("状态文件标记 running=true，上次结晶可能异常终止，已重置")
        return state
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("状态文件损坏 (%s)，使用默认状态: %s", path, exc)
        return CrystallizationState()


def _write_audit_record(
    path: str,
    record: dict[str, Any],
    *,
    max_bytes: int = 0,
    backups: int = 3,
) -> None:
    """Append an audit record to the JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if max_bytes > 0 and p.exists() and p.stat().st_size >= max_bytes:
        for idx in range(max(0, backups - 1), 0, -1):
            src = p.with_suffix(p.suffix + f".{idx}")
            dst = p.with_suffix(p.suffix + f".{idx + 1}")
            if src.exists():
                src.replace(dst)
        p.replace(p.with_suffix(p.suffix + ".1"))
    line = json.dumps(record, ensure_ascii=False)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def finalize_crystallization_state(
    state: CrystallizationState,
    *,
    user_id: str,
    processed_ids: set[str],
    rejected_ids: set[str],
    stale_ids: set[str],
    failed_attempt_ids: set[str],
    max_fact_attempts: int,
    created_count: int,
    absorbed_count: int,
    failed_count: int,
    completed_at: str,
    failed_at: float,
) -> tuple[int, set[str]]:
    failed_attempt_ids.difference_update(processed_ids | rejected_ids | stale_ids)
    evicted_ids: set[str] = set()
    for fact_id in failed_attempt_ids:
        attempts = state.fact_attempts.get(fact_id, 0) + 1
        if attempts >= max_fact_attempts:
            state.fact_attempts.pop(fact_id, None)
            evicted_ids.add(fact_id)
        else:
            state.fact_attempts[fact_id] = attempts

    remove_ids = processed_ids | rejected_ids | stale_ids | evicted_ids
    for fact_id in remove_ids:
        state.fact_attempts.pop(fact_id, None)
    state.pending_ids[user_id] = [
        fact_id for fact_id in state.pending_ids.get(user_id, []) if fact_id not in remove_ids
    ]

    if created_count + absorbed_count:
        state.last_run[user_id] = completed_at
        state.last_failed_attempt.pop(user_id, None)
    elif state.pending_ids[user_id]:
        state.last_failed_attempt[user_id] = failed_at
    else:
        state.last_failed_attempt.pop(user_id, None)
    state.last_check.pop(user_id, None)
    state.last_check_passed.pop(user_id, None)
    state.total_created += created_count
    state.total_absorbed += absorbed_count
    state.total_failed += failed_count
    state.total_rejected += len(rejected_ids)
    state.total_evicted += len(evicted_ids)
    return len(state.pending_ids[user_id]), evicted_ids


def _save_state(state: CrystallizationState, path: str) -> None:
    """Atomically write the state file (write to .tmp first, then rename)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "last_run": state.last_run,
        "last_check": state.last_check,
        "last_check_passed": state.last_check_passed,
        "last_failed_attempt": state.last_failed_attempt,
        "pending_ids": state.pending_ids,
        "fact_attempts": state.fact_attempts,
        "total_created": state.total_created,
        "total_absorbed": state.total_absorbed,
        "total_failed": state.total_failed,
        "total_rejected": state.total_rejected,
        "total_evicted": state.total_evicted,
        "running": state.running,
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
