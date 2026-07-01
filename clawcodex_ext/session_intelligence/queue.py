"""Pending queue for session summary generation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def queue_path(base_dir: Path | None = None) -> Path:
    root = base_dir or (Path.home() / ".clawcodex")
    return root / "session_summaries" / "queue.jsonl"


def enqueue_summary_job(
    session_id: str,
    *,
    cwd: str | Path | None = None,
    transcript_mtime: float = 0.0,
    base_dir: Path | None = None,
) -> Path:
    path = queue_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "session_id": session_id,
        "cwd": str(cwd or ""),
        "transcript_mtime": transcript_mtime,
        "state": "pending",
        "attempts": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if session_id != "latest":
        try:
            from src.services.session_storage import SESSIONS_DIR

            session_dir = (
                Path(base_dir) / "sessions" / session_id
                if base_dir is not None
                else Path(SESSIONS_DIR) / session_id
            )
            write_status(
                session_dir,
                {
                    "state": "pending",
                    "transcript_mtime": transcript_mtime,
                    "attempts": 0,
                    "last_error": "",
                    "updated_at": time.time(),
                },
            )
        except Exception:
            pass
    return path


def write_status(session_dir: Path, status: dict[str, Any]) -> Path:
    path = session_dir / "summary.status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(status)
    payload.setdefault("updated_at", time.time())
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_pending_jobs(*, base_dir: Path | None = None, limit: int = 100) -> list[dict[str, Any]]:
    path = queue_path(base_dir)
    if not path.exists():
        return []
    jobs: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("state", "pending") == "pending":
                jobs.append(data)
    except OSError:
        return []
    return jobs


def process_pending_summary_jobs(
    *,
    base_dir: Path | None = None,
    sessions_dir: Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Best-effort queue drain for missing/stale ``summary.json`` files."""

    from clawcodex_ext.session_intelligence.summarizer import summarize_session

    jobs = read_pending_jobs(base_dir=base_dir, limit=limit)
    processed = 0
    failed = 0
    remaining: list[dict[str, Any]] = []
    for job in jobs:
        session_id = str(job.get("session_id") or "")
        if not session_id or session_id == "latest":
            continue
        result = summarize_session(session_id, sessions_dir=sessions_dir)
        if result.get("generated"):
            processed += 1
        else:
            failed += 1
            retry = dict(job)
            retry["attempts"] = int(retry.get("attempts") or 0) + 1
            retry["last_error"] = str(result.get("reason") or "")
            retry["updated_at"] = time.time()
            if retry["attempts"] < 3:
                remaining.append(retry)

    path = queue_path(base_dir)
    if remaining:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in remaining:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    return {"processed": processed, "failed": failed, "remaining": len(remaining)}


def start_summary_queue_worker(
    *,
    base_dir: Path | None = None,
    sessions_dir: Path | None = None,
    limit: int = 20,
) -> None:
    """Spawn a short-lived daemon worker to drain pending summary jobs."""

    import threading

    def _run() -> None:
        try:
            process_pending_summary_jobs(base_dir=base_dir, sessions_dir=sessions_dir, limit=limit)
        except Exception:
            pass

    thread = threading.Thread(target=_run, name="summary-queue-worker", daemon=True)
    thread.start()
