"""Consolidation lock — F-100 / 100.3.

Mirrors ``typescript/src/services/autoDream/consolidationLock.ts``.
The lock file lives in the auto-memory dir and its mtime *is*
``lastConsolidatedAt``. Body is the holder's PID. Two reclaimers
both write the same PID — last write wins; loser bails on re-read.

Operations:

* :func:`read_last_consolidated_at` — one stat, returns mtime ms.
* :func:`try_acquire_consolidation_lock` — write PID, return prior
  mtime for rollback or ``None`` if blocked.
* :func:`rollback_consolidation_lock` — rewind mtime to prior
  (or unlink if prior was 0).
* :func:`record_consolidation` — optimistic stamp for manual /dream
  (no contention check).
* :func:`list_sessions_touched_since` — session ids with mtime
  after *since_ms* (used by the session gate).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from clawcodex_ext.dreaming.paths import get_auto_mem_path, project_transcript_dir

_log = logging.getLogger(__name__)

LOCK_FILE_NAME = ".consolidate-lock"

# Stale past this even if PID is live (PID-reuse guard). Matches
# upstream ``HOLDER_STALE_MS`` (60min).
HOLDER_STALE_MS = 60 * 60 * 1000


def _lock_path() -> Path:
    return Path(get_auto_mem_path()) / LOCK_FILE_NAME


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read_last_consolidated_at() -> int:
    """mtime of the lock file = lastConsolidatedAt. 0 if absent.

    One stat per call. Used by the time gate.
    """
    try:
        return int(_lock_path().stat().st_mtime * 1000)
    except FileNotFoundError:
        return 0
    except OSError as e:  # pragma: no cover - defensive
        _log.debug("read_last_consolidated_at failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Acquire
# ---------------------------------------------------------------------------


def try_acquire_consolidation_lock() -> int | None:
    """Acquire: write PID → mtime = now. Return the pre-acquire mtime
    (for rollback), or ``None`` if blocked / lost a race.

    * Success → mtime stays at now.
    * Failure → :func:`rollback_consolidation_lock` rewinds mtime.
    * Crash → mtime stuck, dead PID → next process reclaims.
    """
    path = _lock_path()
    mtime_ms: int | None = None
    holder_pid: int | None = None

    if path.exists():
        try:
            st = path.stat()
            mtime_ms = int(st.st_mtime * 1000)
        except OSError:
            mtime_ms = None
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = int(raw.strip())
            holder_pid = parsed if parsed > 0 else None
        except (OSError, ValueError):
            holder_pid = None

    if mtime_ms is not None and _now_ms() - mtime_ms < HOLDER_STALE_MS:
        if holder_pid is not None and _pid_is_alive(holder_pid):
            _log.debug(
                "consolidation lock held by live PID %d (mtime %ds ago)",
                holder_pid,
                (_now_ms() - mtime_ms) // 1000,
            )
            return None
        # Dead PID or unparseable body — reclaim.

    # Ensure the memory dir exists before writing.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:  # pragma: no cover - defensive
        _log.debug("mkdir for consolidation lock failed: %s", e)
        return None

    try:
        path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as e:  # pragma: no cover - defensive
        _log.debug("write consolidation lock failed: %s", e)
        return None

    # Two reclaimers both write → last wins the PID. Loser bails on re-read.
    try:
        verify = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if int(verify) != os.getpid():
        return None

    return mtime_ms or 0


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_consolidation_lock(prior_mtime: int) -> None:
    """Rewind mtime to *prior_mtime* after a failed fork.

    prior_mtime == 0 → unlink (restore "no-file" state). Else write
    empty body + utimes to set mtime. Best-effort — never raises.
    """
    path = _lock_path()
    try:
        if prior_mtime <= 0:
            path.unlink(missing_ok=True)
            return
        path.write_text("", encoding="utf-8")
        seconds = prior_mtime / 1000.0
        os.utime(path, (seconds, seconds))
    except OSError as e:
        _log.debug(
            "consolidation lock rollback failed: %s — next trigger delayed to minHours",
            e,
        )


# ---------------------------------------------------------------------------
# Record (manual /dream optimistic stamp)
# ---------------------------------------------------------------------------


def record_consolidation() -> None:
    """Stamp from manual ``/dream``. Optimistic — fires at
    prompt-build time, no post-skill completion hook. Best-effort."""
    path = _lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as e:  # pragma: no cover - defensive
        _log.debug("record_consolidation write failed: %s", e)


# ---------------------------------------------------------------------------
# Session scan
# ---------------------------------------------------------------------------


def list_sessions_touched_since(since_ms: int) -> list[str]:
    """Session ids in the project transcript dir with mtime after
    *since_ms*.

    The upstream implementation filters by UUID shape and skips
    ``agent-*.jsonl`` files. clawcodex's session storage has a
    different on-disk layout; we filter by suffix and by parseable
    filename instead. Returns ids (not paths) so the caller can
    exclude the current session by id.

    Scans **only** the per-cwd :func:`project_transcript_dir` — never
    falls back to the global session dir. Falling back to the global
    dir would let unrelated projects inflate the session count for
    this dream run.
    """
    try:
        base = Path(project_transcript_dir())
    except Exception as e:  # pragma: no cover - defensive
        _log.debug("project_transcript_dir failed: %s", e)
        return []
    if not base.is_dir():
        return []

    results: list[str] = []
    for child in _iter_candidates(base):
        try:
            if int(child.stat().st_mtime * 1000) > since_ms:
                results.append(child.name)
        except OSError:
            continue
    return results


def _iter_candidates(base: Path) -> Iterable[Path]:
    """Yield candidate session files under *base*.

    Upstream: ``listCandidates(dir, true)`` filters to UUID-shaped
    filenames and excludes ``agent-*.jsonl``. clawcodex session files
    live as ``<session_id>/...`` directories; we treat each
    subdirectory (or ``.jsonl`` file) as a candidate and let the
    caller filter by mtime.
    """
    try:
        for child in sorted(base.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir() or child.suffix == ".jsonl":
                yield child
    except OSError:
        return


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    return int(time_ms())


def time_ms() -> int:
    """Return current wall time in milliseconds. Indirection for tests."""
    import time as _t

    return int(_t.time() * 1000)
