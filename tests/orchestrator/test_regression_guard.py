"""Tests for the git-sync regression guard (defect R1).

The guard closes the "empty test_command == vacuous pass" hole: with no
configured test command, verification now falls back to an auto-detected
suite run compared against the session's start-commit baseline, and only
net-new failures block the push.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from extensions.orchestrator.config.schema import AgentConfig, VerificationConfig
from extensions.orchestrator.git_sync import GitSyncService, VerificationFailed
from extensions.orchestrator.tracker import Intent, TrackerAdapter


class _NullTracker(TrackerAdapter):
    async def fetch_candidate_issues(self):  # pragma: no cover - unused
        return []

    async def fetch_issue_states_by_ids(self, issue_ids):  # pragma: no cover
        return {}

    async def create_comment(self, issue_id, body):  # pragma: no cover - unused
        return None

    async def update_issue_state(self, issue_id, state):  # pragma: no cover
        return None

    async def update_comment(self, issue_id, comment_id, body):  # pragma: no cover
        return None

    async def create_clarification_comment(self, issue_id, body, mentions=None):  # pragma: no cover
        return None

    async def extract_intent_from_labels(self, labels):  # pragma: no cover
        return Intent.NONE

    async def close_pull_request(self, pull_request):  # pragma: no cover
        return False


class _Session:
    def __init__(self, start_commit_sha: str | None = None) -> None:
        self.start_commit_sha = start_commit_sha
        self.verification_status = None
        self.verification_output = None


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# Exits 1 with a pytest-style FAILED line when bug.txt exists next to it,
# 0 otherwise. Committed into the baseline so the same command runs in
# both the workspace and the baseline worktree.
_CHECK_SCRIPT = textwrap.dedent(
    """
    import os
    import sys

    if os.path.exists("bug.txt"):
        print("FAILED tests/test_x.py::test_boom - AssertionError")
        sys.exit(1)
    sys.exit(0)
    """
).strip()


def _init_repo(root: Path, *, with_bug_in_baseline: bool = False) -> str:
    """Create a git repo whose baseline commit carries check.py.

    Returns the baseline commit sha.
    """
    _git(["init"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test User"], root)
    (root / "check.py").write_text(_CHECK_SCRIPT + "\n", encoding="utf-8")
    if with_bug_in_baseline:
        (root / "bug.txt").write_text("already broken\n", encoding="utf-8")
    _git(["add", "-A"], root)
    _git(["commit", "-m", "baseline"], root)
    return _git(["rev-parse", "HEAD"], root)


def _service(**verification_kwargs) -> GitSyncService:
    config = AgentConfig(verification=VerificationConfig(**verification_kwargs))
    return GitSyncService(_NullTracker(), agent_config=config)


def _check_command() -> str:
    return f'"{sys.executable}" check.py'


class TestFallbackDetection(unittest.TestCase):
    def test_no_tests_detected_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _service()
            self.assertEqual(service._detect_fallback_test_command(tmp), "")

    def test_pytest_suite_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp) / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_something.py").write_text(
                "def test_ok():\n    assert True\n", encoding="utf-8"
            )
            service = _service()
            command = service._detect_fallback_test_command(tmp)
            self.assertIn("-m pytest", command)

    def test_explicit_command_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _service(fallback_test_command="make test")
            self.assertEqual(service._detect_fallback_test_command(tmp), "make test")


class TestRegressionGuard(unittest.IsolatedAsyncioTestCase):
    async def test_green_suite_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = _init_repo(root)
            service = _service(fallback_test_command=_check_command())
            status, _ = await service._run_regression_guard(str(root), _Session(sha))
            self.assertEqual(status, "passed")

    async def test_net_new_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = _init_repo(root)
            # The "agent change" introduces the bug after the baseline.
            (root / "bug.txt").write_text("broken by this change\n", encoding="utf-8")
            service = _service(fallback_test_command=_check_command())
            with self.assertRaises(VerificationFailed) as ctx:
                await service._run_regression_guard(str(root), _Session(sha))
            self.assertIn("net-new", str(ctx.exception))
            self.assertIn("tests/test_x.py::test_boom", ctx.exception.output)

    async def test_preexisting_failure_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sha = _init_repo(root, with_bug_in_baseline=True)
            service = _service(fallback_test_command=_check_command())
            status, note = await service._run_regression_guard(str(root), _Session(sha))
            self.assertEqual(status, "passed_preexisting_failures")
            self.assertIn("already", note)

    async def test_red_suite_without_baseline_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "bug.txt").write_text("broken\n", encoding="utf-8")
            service = _service(fallback_test_command=_check_command())
            with self.assertRaises(VerificationFailed) as ctx:
                await service._run_regression_guard(str(root), _Session(None))
            self.assertIn("no", str(ctx.exception).lower())

    async def test_missing_runner_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            service = _service(
                fallback_test_command="definitely-not-a-real-command-xyz"
            )
            status, note = await service._run_regression_guard(str(root), _Session(None))
            # rc 127 on POSIX shells; Windows reports "not recognized".
            self.assertEqual(status, "skipped_no_tests")
            self.assertIn("unavailable", note)

    async def test_no_suite_detected_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = _service()
            status, note = await service._run_regression_guard(tmp, _Session(None))
            self.assertEqual(status, "skipped_no_tests")
            self.assertIn("no test suite detected", note)


class TestPrePushIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_empty_test_command_no_longer_passes_vacuously(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            session = _Session(None)
            service = _service()
            await service._run_pre_push_verification(str(root), session)
            self.assertEqual(session.verification_status, "skipped_no_tests")

    async def test_guard_disabled_restores_vacuous_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            session = _Session(None)
            service = _service(regression_guard=False)
            await service._run_pre_push_verification(str(root), session)
            self.assertEqual(session.verification_status, "passed")

    async def test_configured_test_command_bypasses_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            # A failing fallback would block, but the explicit test_command
            # is green — the guard must not run at all.
            (root / "bug.txt").write_text("broken\n", encoding="utf-8")
            config = AgentConfig(
                test_command=f'"{sys.executable}" -c "print(1)"',
                verification=VerificationConfig(
                    fallback_test_command=_check_command()
                ),
            )
            service = GitSyncService(_NullTracker(), agent_config=config)
            session = _Session(None)
            await service._run_pre_push_verification(str(root), session)
            self.assertEqual(session.verification_status, "passed")


if __name__ == "__main__":
    unittest.main()
