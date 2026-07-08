"""Daemon state file IO (F-84 P84-A).

A single ``DaemonState`` describes the supervisor's identity — its PID,
the working directory it was launched from, when it started, and the
worker kinds it owns. The state is persisted to a JSON file under the
user's ``~/.clawcodex/daemon/`` directory.

The file is written atomically (``.tmp`` + ``os.replace``) so a crash
mid-write can never leave a half-written JSON file behind. ``query``
helpers also auto-clean the file when the supervisor PID is dead —
that prevents stale state from blocking subsequent ``start`` calls.

This module is intentionally dependency-free (no ``asyncio``, no
``pydantic``) so it can be imported from the CLI subprocess (which
runs ``query_daemon_status`` before deciding whether to spawn the
supervisor).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .constants import (
    DAEMON_STATE_DIRNAME,
    DAEMON_STATE_FILENAME_EXT,
    DAEMON_STATE_SUBDIR,
)

logger = logging.getLogger(__name__)


class DaemonStatus(str, Enum):
    """High-level daemon lifecycle status.

    Stored in state files for display but also useful as a return type
    from :func:`query_daemon_status` — tests assert against the
    enum value, not the underlying string.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    STALE = "stale"  #: state file exists but PID is dead
    ERROR = "error"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class DaemonState:
    """Persistent daemon state.

    Persisted to ``~/.clawcodex/daemon/<name>.json``. The ``pid``
    field is the *supervisor's* PID, not a worker PID — workers track
    their own lifecycles in memory only.
    """

    pid: int
    cwd: str
    started_at: str
    worker_kinds: list[str]
    name: str = "remote-control"
    last_status: DaemonStatus = DaemonStatus.RUNNING
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Serialize the enum to its string value so JSON stays portable.
        d["last_status"] = self.last_status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DaemonState":
        kwargs = dict(data)
        status_str = kwargs.pop("last_status", DaemonStatus.RUNNING.value)
        try:
            kwargs["last_status"] = DaemonStatus(status_str)
        except ValueError:
            logger.warning("DaemonState: unknown status %r; defaulting to RUNNING", status_str)
            kwargs["last_status"] = DaemonStatus.RUNNING
        kwargs.setdefault("extra", {})
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_state_dir(state_dir: Path | None = None) -> Path:
    """Return the directory holding daemon state JSON files.

    When *state_dir* is given (e.g. by tests or non-default installs),
    use it verbatim. Otherwise default to ``~/.clawcodex/daemon``.
    """
    if state_dir is not None:
        return state_dir
    return Path.home() / DAEMON_STATE_DIRNAME / DAEMON_STATE_SUBDIR


def get_state_path(name: str, *, state_dir: Path | None = None) -> Path:
    """Return the absolute path of a daemon state file."""
    return get_state_dir(state_dir) / f"{name}{DAEMON_STATE_FILENAME_EXT}"


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def write_daemon_state(state: DaemonState, *, state_dir: Path | None = None) -> Path:
    """Persist *state* atomically.

    Writes to ``<path>.json.tmp`` first, then ``os.replace`` — this
    guarantees that a reader either sees the previous file or the new
    file, never a half-written buffer. Creates parent directories as
    needed.

    Returns the final state path.
    """
    target = get_state_path(state.name, state_dir=state_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
    # Encode once so the atomic replace replaces the bytes we wrote.
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_daemon_state(
    name: str = "remote-control",
    *,
    state_dir: Path | None = None,
) -> DaemonState | None:
    """Load a daemon state from disk.

    Returns ``None`` if the file does not exist or is unreadable. Errors
    other than :class:`FileNotFoundError` are logged at WARNING level
    so callers can decide whether to surface them.
    """
    path = get_state_path(name, state_dir=state_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning("DaemonState: failed to read %s", path, exc_info=True)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("DaemonState: corrupt JSON at %s; ignoring", path)
        return None
    try:
        return DaemonState.from_dict(data)
    except (TypeError, KeyError):
        logger.warning("DaemonState: missing fields in %s; ignoring", path, exc_info=True)
        return None


def remove_daemon_state(
    name: str = "remote-control",
    *,
    state_dir: Path | None = None,
) -> None:
    """Remove a daemon state file. No-op if missing."""
    path = get_state_path(name, state_dir=state_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("DaemonState: failed to remove %s", path, exc_info=True)


# ---------------------------------------------------------------------------
# Process liveness
# ---------------------------------------------------------------------------


def is_process_alive(pid: int) -> bool:
    """Return ``True`` if *pid* is alive on this host.

    Uses ``os.kill(pid, 0)`` (the POSIX signal-zero probe) on POSIX.
    On Windows ``signal.SIG_DFL == 0`` is also supported but the
    semantics differ slightly — Python normalizes this and treats
    ``PermissionError`` as "alive" (the PID exists even if we can't
    signal it). ``ProcessLookupError`` means "definitely dead".
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — treat as alive.
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def query_daemon_status(
    name: str = "remote-control",
    *,
    state_dir: Path | None = None,
) -> tuple[DaemonStatus, DaemonState | None]:
    """Resolve the high-level status of *name*.

    Returns a ``(status, state)`` tuple. ``state`` is ``None`` when the
    status is ``STOPPED`` or ``STALE``. A ``STALE`` result also
    deletes the on-disk file so subsequent ``start`` calls don't see
    ghost state.
    """
    state = read_daemon_state(name, state_dir=state_dir)
    if state is None:
        return DaemonStatus.STOPPED, None
    if is_process_alive(state.pid):
        return DaemonStatus.RUNNING, state
    remove_daemon_state(name, state_dir=state_dir)
    return DaemonStatus.STALE, None


def make_state(
    *,
    pid: int,
    worker_kinds: list[str],
    name: str = "remote-control",
    cwd: Path | None = None,
) -> DaemonState:
    """Build a fresh :class:`DaemonState` with ``started_at`` pre-filled."""
    return DaemonState(
        pid=pid,
        cwd=str((cwd or Path.cwd()).resolve()),
        started_at=_utcnow_iso(),
        worker_kinds=list(worker_kinds),
        name=name,
        last_status=DaemonStatus.RUNNING,
    )
