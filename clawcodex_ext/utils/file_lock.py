"""Cross-platform file-lock utilities.

Provides a safe ``fcntl.flock`` wrapper that degrades gracefully on
Windows (where ``fcntl`` is not available).  All three functions in this
module are no-ops when ``fcntl`` is absent, so callers never need to
branch on ``sys.platform``.

Usage::

    from clawcodex_ext.utils.file_lock import (
        HAS_FLOCK,
        exclusive_file_lock,
        flock_exclusive,
        flock_unlock,
    )

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    if HAS_FLOCK:
        flock_exclusive(fd)          # may raise OSError
    …
    flock_unlock(fd)
    os.close(fd)

Or with the context manager::

    with exclusive_file_lock(lock_path) as fd:
        …
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Iterator

try:
    import fcntl as _fcntl  # type: ignore[import-not-found]

    HAS_FLOCK = True
except ImportError:
    _fcntl = None  # type: ignore[assignment]
    HAS_FLOCK = False


def flock_exclusive(fd: int, non_blocking: bool = False) -> None:
    """Acquire an exclusive ``flock`` on *fd*.

    On Windows this is a no-op.  Raises ``BlockingIOError`` (subclass of
    ``OSError``) when *non_blocking* is ``True`` and the lock is held by
    another process.
    """
    if not HAS_FLOCK or _fcntl is None:
        return
    flags = _fcntl.LOCK_EX
    if non_blocking:
        flags |= _fcntl.LOCK_NB
    _fcntl.flock(fd, flags)


def flock_unlock(fd: int) -> None:
    """Release a ``flock`` on *fd* (no-op on Windows)."""
    if not HAS_FLOCK or _fcntl is None:
        return
    try:
        _fcntl.flock(fd, _fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def exclusive_file_lock(lock_path: str | Path) -> Iterator[int]:
    """Context manager that acquires an exclusive ``flock`` on *lock_path*.

    On Windows no lock is acquired — the FD is still opened and yielded
    so callers get consistent behaviour without branching on ``HAS_FLOCK``.

    Yields the file-descriptor integer (or ``-1`` on Windows when no FD
    was opened — callers that need the FD should use the lower-level
    functions instead).
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        flock_exclusive(fd)
        yield fd
    finally:
        flock_unlock(fd)
        os.close(fd)