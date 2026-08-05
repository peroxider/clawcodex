"""Byte-level snapshot tests for orchestrator ``_status_snapshot``.

P0-3: locks the exact output of ``GitSyncService._status_snapshot`` so
any change to its sorting logic, file-status query, or path-handling
fails the test instead of silently passing. The existing test at
``tests/orchestrator/test_orchestrator_git_sync.py:439-468`` only
asserts ``before == after`` (self-consistent but wrong passes); these
cases pin the *literal* expected output.

CLAUDE.md notes this was bugged until 2026-06-01 (crashed on
``FileStatus`` until the ``sorted(s.path for s in ...)`` rewrite) — the
test that follow locks the post-fix sort contract.

All cases use the shared ``isolated_tmp_repo`` fixture
(``tests/stability_gate/conftest.py``) which initializes a minimal git
repo on ``tmp_path`` with deterministic identity and ``-b main`` for
the default branch name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from extensions.orchestrator.git_sync import GitSyncService
from extensions.orchestrator.tracker import TrackerAdapter


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


class _StubTracker(TrackerAdapter):
    """Minimal TrackerAdapter — ``_status_snapshot`` does not call the tracker."""

    async def fetch_candidate_issues(self):  # type: ignore[override]
        return []

    async def fetch_issue_states_by_ids(self, ids):  # type: ignore[override]
        return {}

    async def create_comment(self, *a, **k):  # type: ignore[override]
        return None

    async def update_comment(self, *a, **k):  # type: ignore[override]
        return None

    async def create_clarification_comment(self, *a, **k):  # type: ignore[override]
        return None

    async def extract_intent_from_labels(self, *a, **k):  # type: ignore[override]
        return Intent.NONE

    async def close_pull_request(self, *a, **k):  # type: ignore[override]
        return False

    async def update_issue_state(self, *a, **k):  # type: ignore[override]
        return None

    async def ensure_pull_request(self, *a, **k):  # type: ignore[override]
        return None

    async def find_open_pr_for_branch(self, *a, **k):  # type: ignore[override]
        return None


def _snapshot(repo_root: Path) -> str:
    return GitSyncService(tracker=_StubTracker())._status_snapshot(str(repo_root))


class TestStatusSnapshot:
    """Byte-level snapshot for ``GitSyncService._status_snapshot``."""

    def test_no_modifications_returns_empty(self, isolated_tmp_repo: Path):
        """Init + commit, no edits → empty string (NOT ``None``, NOT ``'\\n'``).

        Locks the "nothing to do" sentinel — a regression that returned
        ``None`` would crash the ``f"changed files:\\n{snapshot}"`` call
        site in ``GitSyncService.sync`` with a ``TypeError``. Also
        verifies the ``"\\n".join([]) == ""`` Python semantics is
        preserved end-to-end (the ``get_file_status`` empty-list path).
        """
        (isolated_tmp_repo / "a.txt").write_text("a")
        _git(["add", "."], isolated_tmp_repo)
        _git(["commit", "-m", "init"], isolated_tmp_repo)
        # No subsequent edits — only the initial commit exists.
        assert _snapshot(isolated_tmp_repo) == ""

    def test_single_modified_file(self, isolated_tmp_repo: Path):
        """One tracked file modified → ``'a.txt'`` (no trailing newline).

        Locks the single-file case so a future change that pads with
        ``"\\n"`` or wraps the path (e.g. ``"M a.txt"``) is caught.
        """
        (isolated_tmp_repo / "a.txt").write_text("a")
        _git(["add", "."], isolated_tmp_repo)
        _git(["commit", "-m", "init"], isolated_tmp_repo)
        (isolated_tmp_repo / "a.txt").write_text("a-modified")
        assert _snapshot(isolated_tmp_repo) == "a.txt"

    def test_multiple_files_sorted_by_path(self, isolated_tmp_repo: Path):
        """Multiple files → newline-joined, sorted ASCII-by-path.

        Locks the ``sorted(s.path for s in ...)`` ordering — this is
        the CLAUDE.md-cited key fix from 2026-06-01. A regression that
        sorted by ``str(s)`` (the original bug) would compare
        ``FileStatus(path=...)`` strings and crash because the
        dataclass repr includes the status code.
        """
        for name in ("b.txt", "a.txt", "c.txt"):
            (isolated_tmp_repo / name).write_text(name)
        _git(["add", "."], isolated_tmp_repo)
        _git(["commit", "-m", "init"], isolated_tmp_repo)
        # Modify all three — output order must be a.txt < b.txt < c.txt.
        for name in ("a.txt", "b.txt", "c.txt"):
            (isolated_tmp_repo / name).write_text(name + "-v2")
        assert _snapshot(isolated_tmp_repo) == "a.txt\nb.txt\nc.txt"

    def test_subdirectory_untracked_sorts_after_toplevel(self, isolated_tmp_repo: Path):
        """Untracked subdirectory appears as ``src/`` (not nested paths).

        Git porcelain's default behavior collapses untracked
        subdirectory contents into a single ``src/`` entry — the
        nested ``src/cli.py`` is NOT listed separately. Locks this
        quirk: a future git version or a flag change
        (``--untracked-files=all``) that starts emitting nested paths
        must surface here.
        """
        (isolated_tmp_repo / "a.txt").write_text("a")
        _git(["add", "."], isolated_tmp_repo)
        _git(["commit", "-m", "init"], isolated_tmp_repo)
        # Modify a tracked file; add an untracked top-level directory
        # containing a nested file. Porcelain reports only ``src/``.
        (isolated_tmp_repo / "a.txt").write_text("a-modified")
        (isolated_tmp_repo / "src").mkdir()
        (isolated_tmp_repo / "src" / "cli.py").write_text("x")
        assert _snapshot(isolated_tmp_repo) == "a.txt\nsrc/"

    def test_modified_and_untracked_appear_sorted(self, isolated_tmp_repo: Path):
        """Tracked modifications + untracked new files appear together, sorted.

        Locks that ``get_file_status`` does not silently filter
        untracked entries (the agent-runner uses the snapshot to decide
        whether to run pre-commit hooks — an untracked file should
        count as "dirty"). Both categories are sorted together by path.
        """
        (isolated_tmp_repo / "tracked.txt").write_text("t")
        _git(["add", "."], isolated_tmp_repo)
        _git(["commit", "-m", "init"], isolated_tmp_repo)
        (isolated_tmp_repo / "tracked.txt").write_text("t-v2")  # modified
        (isolated_tmp_repo / "new.txt").write_text("n")  # untracked
        assert _snapshot(isolated_tmp_repo) == "new.txt\ntracked.txt"
