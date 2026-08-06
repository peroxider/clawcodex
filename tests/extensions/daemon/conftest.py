"""Shared fixtures for daemon tests.

Every test gets an isolated, tmp-path-based state directory so
``write_daemon_state`` / ``remove_daemon_state`` never touch the
user's real ``~/.clawcodex/daemon/`` tree.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def state_dir(tmp_path):
    """Per-test daemon state directory (a child of pytest's tmp_path)."""
    d = tmp_path / "daemon"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def worker_kind() -> str:
    """Worker kind used by lifecycle tests."""
    return "test-echo"


@pytest.fixture
def short_backoff():
    """A trivial config patcher that shrinks backoff to ms for tests."""
    from extensions.daemon import constants

    original = constants.BACKOFF_INITIAL_MS
    constants.BACKOFF_INITIAL_MS = 50
    constants.BACKOFF_CAP_MS = 200
    constants.RAPID_FAILURE_WINDOW_MS = 500
    constants.MAX_RAPID_FAILURES = 3
    try:
        yield
    finally:
        constants.BACKOFF_INITIAL_MS = original
        constants.BACKOFF_CAP_MS = 120_000
        constants.RAPID_FAILURE_WINDOW_MS = 10_000
        constants.MAX_RAPID_FAILURES = 5
