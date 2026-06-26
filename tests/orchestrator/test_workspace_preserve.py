"""Tests for workspace conditional preservation policy.

Tests the decision matrix for workspace cleanup:
- completed → preserve_on_terminal
- failed/verification_failed → preserve_on_failure
- abandoned → preserve_on_abandoned
- timeout/budget_exhausted/stagnation → preserve_on_timeout
- others/None → preserve_on_terminal (default)

Also tests:
- run_terminal_workspace_cleanup() respects .workspace_preserved.json
- _write_preservation_manifest() writes correct metadata
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from extensions.orchestrator.workspace import WorkspaceConfig, WorkspaceManager


class _FakeIssue(SimpleNamespace):
    """Minimal issue object for workspace tests."""

    def __init__(self, issue_id: str = "issue-1", identifier: str = "test-issue-1") -> None:
        super().__init__(id=issue_id, identifier=identifier)


class TestShouldPreserve(unittest.TestCase):
    """Test the _should_preserve() decision matrix."""

    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())

    def _make_manager(self, **kwargs: bool) -> WorkspaceManager:
        config = WorkspaceConfig(
            root=self._tmpdir,
            preserve_on_terminal=kwargs.get("preserve_on_terminal", True),
            preserve_on_failure=kwargs.get("preserve_on_failure", True),
            preserve_on_abandoned=kwargs.get("preserve_on_abandoned", True),
            preserve_on_timeout=kwargs.get("preserve_on_timeout", True),
        )
        return WorkspaceManager(config)

    # -- completed --
    def test_completed_preserve_when_enabled(self) -> None:
        mgr = self._make_manager(preserve_on_terminal=True)
        self.assertTrue(mgr._should_preserve("completed", "task_complete"))

    def test_completed_delete_when_disabled(self) -> None:
        mgr = self._make_manager(preserve_on_terminal=False)
        self.assertFalse(mgr._should_preserve("completed", "task_complete"))

    # -- failed --
    def test_failed_preserve_when_enabled(self) -> None:
        mgr = self._make_manager(preserve_on_failure=True)
        self.assertTrue(mgr._should_preserve("failed", None))

    def test_failed_delete_when_disabled(self) -> None:
        mgr = self._make_manager(preserve_on_failure=False)
        self.assertFalse(mgr._should_preserve("failed", None))

    def test_verification_failed_preserve(self) -> None:
        mgr = self._make_manager(preserve_on_failure=True)
        self.assertTrue(mgr._should_preserve("verification_failed", None))

    # -- abandoned --
    def test_abandoned_preserve_when_enabled(self) -> None:
        mgr = self._make_manager(preserve_on_abandoned=True)
        self.assertTrue(mgr._should_preserve("abandoned", "stagnation"))

    def test_abandoned_delete_when_disabled(self) -> None:
        mgr = self._make_manager(preserve_on_abandoned=False)
        self.assertFalse(mgr._should_preserve("abandoned", "stagnation"))

    # -- timeout / budget_exhausted / stagnation --
    def test_budget_exhausted_preserve_when_enabled(self) -> None:
        mgr = self._make_manager(preserve_on_timeout=True)
        self.assertTrue(mgr._should_preserve("failed", "budget_exhausted"))

    def test_budget_exhausted_delete_when_disabled(self) -> None:
        mgr = self._make_manager(preserve_on_timeout=False)
        self.assertFalse(mgr._should_preserve("failed", "budget_exhausted"))

    def test_stagnation_preserve(self) -> None:
        # stagnation is an abandoned-specific reason → uses preserve_on_abandoned
        mgr = self._make_manager(preserve_on_abandoned=True)
        self.assertTrue(mgr._should_preserve("abandoned", "stagnation"))

    def test_stagnation_delete_when_abandoned_disabled(self) -> None:
        mgr = self._make_manager(preserve_on_abandoned=False)
        self.assertFalse(mgr._should_preserve("abandoned", "stagnation"))

    def test_loop_detected_preserve(self) -> None:
        # loop_detected is an abandoned-specific reason → uses preserve_on_abandoned
        mgr = self._make_manager(preserve_on_abandoned=True)
        self.assertTrue(mgr._should_preserve("abandoned", "loop_detected"))

    # -- None / unknown → defaults to preserve_on_terminal --
    def test_none_status_uses_preserve_on_terminal(self) -> None:
        mgr_enabled = self._make_manager(preserve_on_terminal=True)
        self.assertTrue(mgr_enabled._should_preserve(None, None))

        mgr_disabled = self._make_manager(preserve_on_terminal=False)
        self.assertFalse(mgr_disabled._should_preserve(None, None))

    def test_unknown_status_uses_preserve_on_terminal(self) -> None:
        mgr = self._make_manager(preserve_on_terminal=False)
        self.assertFalse(mgr._should_preserve("some_unknown_status", None))

    # -- cancelled → uses preserve_on_terminal --
    def test_cancelled_uses_preserve_on_terminal(self) -> None:
        mgr_enabled = self._make_manager(preserve_on_terminal=True)
        self.assertTrue(mgr_enabled._should_preserve("cancelled", "operator_stopped"))

        mgr_disabled = self._make_manager(preserve_on_terminal=False)
        self.assertFalse(mgr_disabled._should_preserve("cancelled", "operator_stopped"))

    # -- case insensitivity --
    def test_case_insensitive_status(self) -> None:
        mgr = self._make_manager(preserve_on_failure=True)
        self.assertTrue(mgr._should_preserve("FAILED", None))
        self.assertTrue(mgr._should_preserve("Failed", None))

    def test_case_insensitive_reason(self) -> None:
        mgr = self._make_manager(preserve_on_timeout=True)
        self.assertTrue(mgr._should_preserve("failed", "BUDGET_EXHAUSTED"))


class TestCleanupPreservation(unittest.IsolatedAsyncioTestCase):
    """Test cleanup() with preservation logic."""

    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())

    def _make_manager(self, **kwargs: bool) -> WorkspaceManager:
        config = WorkspaceConfig(
            root=self._tmpdir,
            preserve_on_terminal=kwargs.get("preserve_on_terminal", True),
            preserve_on_failure=kwargs.get("preserve_on_failure", True),
            preserve_on_abandoned=kwargs.get("preserve_on_abandoned", True),
            preserve_on_timeout=kwargs.get("preserve_on_timeout", True),
        )
        return WorkspaceManager(config)

    async def test_cleanup_preserves_when_policy_says_true(self) -> None:
        """Workspace directory should survive cleanup when preserve=True."""
        mgr = self._make_manager(preserve_on_terminal=True)
        issue = _FakeIssue(identifier="issue-preserve")
        ws_path = mgr._build_path("issue-preserve")
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "test.txt").write_text("hello")

        await mgr.cleanup(issue, end_status="completed", end_reason="task_complete")

        self.assertTrue(ws_path.exists())
        self.assertTrue((ws_path / "test.txt").exists())

    async def test_cleanup_deletes_when_policy_says_false(self) -> None:
        """Workspace directory should be removed when preserve=False."""
        mgr = self._make_manager(preserve_on_terminal=False)
        issue = _FakeIssue(identifier="issue-delete")
        ws_path = mgr._build_path("issue-delete")
        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "test.txt").write_text("hello")

        await mgr.cleanup(issue, end_status="completed", end_reason="task_complete")

        self.assertFalse(ws_path.exists())

    async def test_cleanup_preserves_on_failure(self) -> None:
        """Failed workspace should be preserved when preserve_on_failure=True."""
        mgr = self._make_manager(preserve_on_failure=True)
        issue = _FakeIssue(identifier="issue-failed")
        ws_path = mgr._build_path("issue-failed")
        ws_path.mkdir(parents=True, exist_ok=True)

        await mgr.cleanup(issue, end_status="failed", end_reason=None)

        self.assertTrue(ws_path.exists())

    async def test_cleanup_deletes_failed_when_disabled(self) -> None:
        """Failed workspace should be deleted when preserve_on_failure=False."""
        mgr = self._make_manager(preserve_on_failure=False)
        issue = _FakeIssue(identifier="issue-fail-delete")
        ws_path = mgr._build_path("issue-fail-delete")
        ws_path.mkdir(parents=True, exist_ok=True)

        await mgr.cleanup(issue, end_status="failed", end_reason=None)

        self.assertFalse(ws_path.exists())

    async def test_cleanup_preserves_on_abandoned(self) -> None:
        """Abandoned workspace should be preserved when preserve_on_abandoned=True."""
        mgr = self._make_manager(preserve_on_abandoned=True)
        issue = _FakeIssue(identifier="issue-abandoned")
        ws_path = mgr._build_path("issue-abandoned")
        ws_path.mkdir(parents=True, exist_ok=True)

        await mgr.cleanup(issue, end_status="abandoned", end_reason="stagnation")

        self.assertTrue(ws_path.exists())

    async def test_cleanup_writes_manifest_when_preserved(self) -> None:
        """Preservation should write .workspace_preserved.json with metadata."""
        mgr = self._make_manager(preserve_on_terminal=True)
        issue = _FakeIssue(issue_id="42", identifier="issue-manifest")
        ws_path = mgr._build_path("issue-manifest")
        ws_path.mkdir(parents=True, exist_ok=True)

        await mgr.cleanup(issue, end_status="completed", end_reason="task_complete")

        manifest_path = ws_path / ".orchestrator_workspace" / ".workspace_preserved.json"
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["issue_id"], "42")
        self.assertEqual(manifest["identifier"], "issue-manifest")
        self.assertEqual(manifest["end_status"], "completed")
        self.assertEqual(manifest["end_reason"], "task_complete")
        self.assertIn("preserved_at", manifest)

    async def test_cleanup_no_args_defaults_to_preserve_on_terminal(self) -> None:
        """cleanup() called without args should use preserve_on_terminal (True by default)."""
        mgr = self._make_manager()  # all defaults True
        issue = _FakeIssue(identifier="issue-default")
        ws_path = mgr._build_path("issue-default")
        ws_path.mkdir(parents=True, exist_ok=True)

        await mgr.cleanup(issue)

        self.assertTrue(ws_path.exists())


class TestTerminalWorkspaceCleanup(unittest.IsolatedAsyncioTestCase):
    """Test run_terminal_workspace_cleanup() respecting preservation manifests."""

    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())

    def _make_manager(self) -> WorkspaceManager:
        config = WorkspaceConfig(root=self._tmpdir)
        return WorkspaceManager(config)

    async def test_orphaned_workspaces_are_deleted(self) -> None:
        """Workspaces without .workspace_preserved.json should be cleaned on startup."""
        mgr = self._make_manager()
        orphan = self._tmpdir / "orphan-issue"
        orphan.mkdir()
        (orphan / "code.py").write_text("print('orphan')")

        await mgr.run_terminal_workspace_cleanup()

        self.assertFalse(orphan.exists())

    async def test_preserved_workspaces_are_kept(self) -> None:
        """Workspaces with .workspace_preserved.json should survive startup cleanup."""
        mgr = self._make_manager()
        preserved = self._tmpdir / "preserved-issue"
        preserved.mkdir()
        (preserved / "code.py").write_text("print('preserved')")
        (preserved / ".orchestrator_workspace").mkdir(exist_ok=True)
        manifest = preserved / ".orchestrator_workspace" / ".workspace_preserved.json"
        manifest.write_text(
            json.dumps(
                {
                    "issue_id": "1",
                    "identifier": "preserved-issue",
                    "preserved_at": 1000.0,
                    "end_status": "completed",
                    "end_reason": "task_complete",
                }
            )
        )

        await mgr.run_terminal_workspace_cleanup()

        self.assertTrue(preserved.exists())
        self.assertTrue((preserved / "code.py").exists())

    async def test_mixed_orphaned_and_preserved(self) -> None:
        """Only orphaned workspaces should be deleted; preserved ones should remain."""
        mgr = self._make_manager()

        # Create orphaned workspace
        orphan = self._tmpdir / "orphan-issue"
        orphan.mkdir()

        # Create preserved workspace
        preserved = self._tmpdir / "preserved-issue"
        preserved.mkdir()
        (preserved / ".orchestrator_workspace").mkdir(exist_ok=True)
        (preserved / ".orchestrator_workspace" / ".workspace_preserved.json").write_text("{}")

        await mgr.run_terminal_workspace_cleanup()

        self.assertFalse(orphan.exists(), "Orphan should be deleted")
        self.assertTrue(preserved.exists(), "Preserved should survive")

    async def test_non_isolated_strategy_skips_cleanup(self) -> None:
        """Non-isolated strategies should skip terminal cleanup entirely."""
        config = WorkspaceConfig(root=self._tmpdir, strategy="shared")
        mgr = WorkspaceManager(config)
        ws = self._tmpdir / "shared-issue"
        ws.mkdir()

        await mgr.run_terminal_workspace_cleanup()

        self.assertTrue(ws.exists(), "Shared workspace should not be touched")


class TestWritePreservationManifest(unittest.IsolatedAsyncioTestCase):
    """Test _write_preservation_manifest() writes correct JSON."""

    def setUp(self) -> None:
        self._tmpdir = Path(tempfile.mkdtemp())

    def _make_manager(self) -> WorkspaceManager:
        config = WorkspaceConfig(root=self._tmpdir)
        return WorkspaceManager(config)

    async def test_manifest_contains_all_fields(self) -> None:
        mgr = self._make_manager()
        ws_path = self._tmpdir / "test-issue"
        ws_path.mkdir()
        issue = _FakeIssue(issue_id="99", identifier="test-issue")

        await mgr._write_preservation_manifest(ws_path, issue, "completed", "task_complete")

        manifest_path = ws_path / ".orchestrator_workspace" / ".workspace_preserved.json"
        self.assertTrue(manifest_path.exists())

        data = json.loads(manifest_path.read_text())
        self.assertEqual(data["issue_id"], "99")
        self.assertEqual(data["identifier"], "test-issue")
        self.assertEqual(data["end_status"], "completed")
        self.assertEqual(data["end_reason"], "task_complete")
        self.assertIsInstance(data["preserved_at"], float)

    async def test_manifest_handles_none_values(self) -> None:
        mgr = self._make_manager()
        ws_path = self._tmpdir / "none-issue"
        ws_path.mkdir()
        issue = _FakeIssue(issue_id=None, identifier="none-issue")

        await mgr._write_preservation_manifest(ws_path, issue, None, None)

        data = json.loads(
            (ws_path / ".orchestrator_workspace" / ".workspace_preserved.json").read_text()
        )
        self.assertIsNone(data["issue_id"])
        self.assertIsNone(data["end_status"])
        self.assertIsNone(data["end_reason"])


if __name__ == "__main__":
    unittest.main()
