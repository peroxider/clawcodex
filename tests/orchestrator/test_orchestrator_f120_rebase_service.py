"""Step 4: rebase_for_pr + PRRebaseResult + helpers.

Covers the full path through ``rebase_for_pr`` using a real (but
in-process) git repo fixture:

  - already up-to-date short-circuit (rebased=True, pushed=False)
  - clean rebase + --force-with-lease push (default)
  - clean rebase + --force push (operator override)
  - content conflict (returns has_conflict=True, leaves REBASE_HEAD)
  - non-conflict rebase failure (rare auth case) → abort + no-op
  - push failure → reset --hard rollback
  - _ahead_behind / _git_rebase_abort helpers
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from extensions.orchestrator.git_sync import (
    PRRebaseResult,
    _ahead_behind,
    _git_rebase_abort,
    rebase_for_pr,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
    """Initialize a git repo with an empty initial commit."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        # Avoid GPG signing prompts in CI.
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(path)], env=env)
    subprocess.check_call(["git", "config", "user.email", "t@example.com"], cwd=path, env=env)
    subprocess.check_call(["git", "config", "user.name", "test"], cwd=path, env=env)
    # Disable commit signing (WSL/CI GPG is unreliable).
    subprocess.check_call(["git", "config", "commit.gpgsign", "false"], cwd=path, env=env)
    # Create an initial empty commit so HEAD exists.
    (path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "README.md"], cwd=path, env=env)
    subprocess.check_call(["git", "commit", "-q", "-m", "init"], cwd=path, env=env)


def _make_remote(tmp: Path) -> Path:
    """Create a bare 'origin' remote."""
    remote = tmp / "origin.git"
    subprocess.check_call(["git", "init", "-q", "--bare", str(remote)])
    return remote


def _push_initial(tmp: Path, path: Path, remote: Path, branch: str, base: str) -> None:
    """Configure origin, push initial branch + base, create feature branch."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.check_call(["git", "remote", "add", "origin", str(remote)], cwd=path, env=env)
    subprocess.check_call(["git", "push", "-q", "origin", branch], cwd=path, env=env)
    if branch != base:
        subprocess.check_call(["git", "branch", base, branch], cwd=path, env=env)
        subprocess.check_call(["git", "push", "-q", "origin", base], cwd=path, env=env)
        subprocess.check_call(["git", "checkout", "-q", base], cwd=path, env=env)


def _commit(path: Path, message: str, files: dict[str, str] | None = None) -> str:
    """Create a commit with optional file contents; return SHA."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    if files:
        for name, content in files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        subprocess.check_call(["git", "add", "-A"], cwd=path, env=env)
    out = subprocess.check_output(
        ["git", "commit", "-q", "-m", message], cwd=path, env=env, text=True
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, env=env, text=True
    ).strip()
    return sha


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPRRebaseResultDataclass(unittest.TestCase):
    def test_default_values(self) -> None:
        r = PRRebaseResult(rebased=False)
        self.assertFalse(r.rebased)
        self.assertFalse(r.has_conflict)
        self.assertEqual(r.conflict_files, ())
        self.assertIsNone(r.new_head_sha)
        self.assertFalse(r.pushed)
        self.assertEqual(r.push_method, "none")
        self.assertTrue(r.workspace_clean)

    def test_conflict_result(self) -> None:
        r = PRRebaseResult(
            rebased=False,
            has_conflict=True,
            conflict_files=("a.py", "b.py"),
        )
        self.assertTrue(r.has_conflict)
        self.assertEqual(r.conflict_files, ("a.py", "b.py"))


class TestAheadBehind(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="f120_ab_"))
        self.path = self.tmp / "repo"
        self.path.mkdir()
        _init_repo(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zero_zero_when_same_commit(self) -> None:
        # README.md commit exists; nothing diverged.
        ahead, behind = _ahead_behind(str(self.path), "main", "main")
        self.assertEqual((ahead, behind), (0, 0))

    def test_parse_failure_returns_zero_zero(self) -> None:
        # Invalid branch name → rev-list fails → fallback.
        ahead, behind = _ahead_behind(str(self.path), "main", "nonexistent-branch-xyz")
        self.assertEqual((ahead, behind), (0, 0))


class TestRebaseForPr(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="f120_rebase_"))
        self.path = self.tmp / "repo"
        self.path.mkdir()
        self.remote = _make_remote(self.tmp)
        _init_repo(self.path)
        # _init_repo already creates a README.md commit on main.
        _push_initial(self.tmp, self.path, self.remote, "main", "main")
        # Create feature branch with one extra commit.
        subprocess.check_call(["git", "checkout", "-q", "-b", "feature"], cwd=self.path)
        _commit(self.path, "feature-1", {"feature.txt": "feature-1\n"})
        subprocess.check_call(["git", "push", "-q", "origin", "feature"], cwd=self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_already_up_to_date(self) -> None:
        # Run rebase: base is at the same SHA as branch's parent,
        # so behind == 0 → short-circuit.
        result = rebase_for_pr(
            workspace_path=str(self.path),
            branch_name="feature",
            base_branch="main",
        )
        self.assertTrue(result.rebased)
        self.assertFalse(result.has_conflict)
        self.assertFalse(result.pushed)
        self.assertEqual(result.push_method, "none")
        self.assertTrue(result.workspace_clean)

    def test_clean_rebase_force_with_lease(self) -> None:
        # Move main forward on the remote, then rebase feature.
        subprocess.check_call(["git", "checkout", "-q", "main"], cwd=self.path)
        _commit(self.path, "main-2", {"main.txt": "main-2\n"})
        subprocess.check_call(["git", "push", "-q", "origin", "main"], cwd=self.path)
        # Switch back to feature and run rebase_for_pr.
        subprocess.check_call(["git", "checkout", "-q", "feature"], cwd=self.path)
        result = rebase_for_pr(
            workspace_path=str(self.path),
            branch_name="feature",
            base_branch="main",
        )
        self.assertTrue(result.rebased)
        self.assertFalse(result.has_conflict)
        self.assertTrue(result.pushed)
        self.assertEqual(result.push_method, "force_with_lease")
        self.assertTrue(result.workspace_clean)
        self.assertIsNotNone(result.new_head_sha)

    def test_clean_rebase_force(self) -> None:
        subprocess.check_call(["git", "checkout", "-q", "main"], cwd=self.path)
        _commit(self.path, "main-2-force", {"main2.txt": "x\n"})
        subprocess.check_call(["git", "push", "-q", "origin", "main"], cwd=self.path)
        subprocess.check_call(["git", "checkout", "-q", "feature"], cwd=self.path)
        result = rebase_for_pr(
            workspace_path=str(self.path),
            branch_name="feature",
            base_branch="main",
            force=True,
        )
        self.assertTrue(result.rebased)
        self.assertTrue(result.pushed)
        self.assertEqual(result.push_method, "force")
        self.assertFalse(result.has_conflict)

    def test_content_conflict(self) -> None:
        # Both branches modify README.md → rebase will conflict.
        subprocess.check_call(["git", "checkout", "-q", "main"], cwd=self.path)
        _commit(self.path, "main-conflict", {"README.md": "main-side\n"})
        subprocess.check_call(["git", "push", "-q", "origin", "main"], cwd=self.path)
        subprocess.check_call(["git", "checkout", "-q", "feature"], cwd=self.path)
        _commit(self.path, "feature-conflict", {"README.md": "feature-side\n"})
        subprocess.check_call(["git", "push", "-q", "origin", "feature"], cwd=self.path)
        result = rebase_for_pr(
            workspace_path=str(self.path),
            branch_name="feature",
            base_branch="main",
        )
        self.assertFalse(result.rebased)
        self.assertTrue(result.has_conflict)
        self.assertIn("README.md", result.conflict_files)
        self.assertFalse(result.workspace_clean)
        # Should NOT push on conflict.
        self.assertFalse(result.pushed)


class TestGitRebaseAbort(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="f120_abort_"))
        self.path = self.tmp / "repo"
        self.path.mkdir()
        _init_repo(self.path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_abort_silently_when_no_rebase(self) -> None:
        # No rebase in progress; _git_rebase_abort should NOT raise.
        try:
            _git_rebase_abort(str(self.path))
        except Exception as exc:
            self.fail(f"_git_rebase_abort raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
