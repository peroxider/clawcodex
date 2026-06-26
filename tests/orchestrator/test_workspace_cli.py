"""Tests for workspace CLI commands (Phase 2).

Tests the workspace management CLI subcommands:
- workspace list
- workspace show
- workspace cd
- workspace cleanup
- workspace verify
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

import pytest

from extensions.orchestrator.cli.workspace import (
    _cmd_list,
    _cmd_show,
    _cmd_cd,
    _cmd_cleanup,
    _cmd_verify,
)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory with test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_root = Path(tmpdir)

        # Create a few test workspaces
        ws1 = workspace_root / "issue-123"
        ws1.mkdir()
        (ws1 / ".orchestrator_workspace").mkdir()
        manifest1 = ws1 / ".orchestrator_workspace" / ".workspace_preserved.json"
        manifest1.write_text(
            json.dumps(
                {
                    "issue_id": "123",
                    "end_status": "completed",
                    "branch": "fix/issue-123",
                    "commit_sha": "abc123def456",
                    "preserved_at": 1719225600,  # 2024-06-24 10:00:00 UTC
                }
            )
        )

        ws2 = workspace_root / "issue-456"
        ws2.mkdir()
        (ws2 / ".orchestrator_workspace").mkdir()
        manifest2 = ws2 / ".orchestrator_workspace" / ".workspace_preserved.json"
        manifest2.write_text(
            json.dumps(
                {
                    "issue_id": "456",
                    "end_status": "failed",
                    "branch": "feat/issue-456",
                    "commit_sha": "def789abc012",
                    "preserved_at": 1719229200,  # 2024-06-24 11:00:00 UTC
                }
            )
        )

        # Create a non-preserved workspace (no manifest)
        ws3 = workspace_root / "issue-789"
        ws3.mkdir()

        yield workspace_root


@pytest.fixture
def temp_registry(temp_workspace):
    """Return None to skip registry loading in tests.

    The workspace commands can work without a registry by using
    the .workspace_preserved.json manifest files directly.
    """
    yield None


class TestListWorkspaces:
    """Tests for _cmd_list function."""

    def test_list_all_workspaces(self, temp_workspace, temp_registry, capsys):
        """Test listing all preserved workspaces."""
        args = Namespace(status=None)
        _cmd_list(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        assert "issue-123" in captured.out
        assert "issue-456" in captured.out
        assert "completed" in captured.out
        assert "failed" in captured.out

    def test_list_filtered_by_status(self, temp_workspace, temp_registry, capsys):
        """Test listing workspaces filtered by status."""
        args = Namespace(status="completed")
        _cmd_list(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        assert "issue-123" in captured.out
        assert "issue-456" not in captured.out

    def test_list_empty_workspace_root(self, temp_registry, capsys):
        """Test listing when workspace root is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = Namespace(status=None)
            _cmd_list(Path(tmpdir), temp_registry, args)

            captured = capsys.readouterr()
            assert "No preserved workspaces found" in captured.out

    def test_list_skips_non_preserved_workspaces(self, temp_workspace, temp_registry, capsys):
        """Test that non-preserved workspaces are not listed."""
        args = Namespace(status=None)
        _cmd_list(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        # issue-789 has no manifest, should not be listed
        assert "issue-789" not in captured.out


class TestShowWorkspace:
    """Tests for _cmd_show function."""

    def test_show_workspace_details(self, temp_workspace, temp_registry, capsys):
        """Test showing workspace details."""
        args = Namespace(id="123")
        _cmd_show(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        assert "123" in captured.out
        assert "completed" in captured.out
        # Branch and commit info come from registry, not manifest
        # When registry is None, these fields won't be shown
        # Just verify the workspace path is shown
        assert "issue-123" in captured.out

    def test_show_workspace_without_manifest(self, temp_workspace, temp_registry, capsys):
        """Test showing workspace without manifest."""
        args = Namespace(id="789")
        _cmd_show(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        # Error message goes to stderr
        # Check for either "No preserved workspace found" or "No preservation manifest"
        assert (
            "No preserved workspace found" in captured.err
            or "No preservation manifest" in captured.err
        )


class TestGetWorkspacePath:
    """Tests for _cmd_cd function."""

    def test_get_existing_workspace_path(self, temp_workspace, temp_registry, capsys):
        """Test getting path for existing workspace."""
        args = Namespace(id="123")
        result = _cmd_cd(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        assert str(temp_workspace / "issue-123") in captured.out
        assert result == 0

    def test_get_nonexistent_workspace_path(self, temp_workspace, temp_registry, capsys):
        """Test getting path for non-existent workspace."""
        args = Namespace(id="999")
        result = _cmd_cd(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        # Error message goes to stderr
        assert "No preserved workspace found" in captured.err
        assert result == 1


class TestCleanupWorkspace:
    """Tests for _cmd_cleanup function."""

    def test_cleanup_with_force(self, temp_workspace, temp_registry):
        """Test cleanup with --force flag."""
        ws_path = temp_workspace / "issue-123"
        assert ws_path.exists()

        args = Namespace(id="123", force=True)
        result = _cmd_cleanup(temp_workspace, temp_registry, args)

        assert not ws_path.exists()
        assert result == 0

    def test_cleanup_without_force_prompts(self, temp_workspace, temp_registry, monkeypatch):
        """Test cleanup without --force prompts for confirmation."""
        ws_path = temp_workspace / "issue-123"

        # Simulate user saying "yes"
        monkeypatch.setattr("builtins.input", lambda _: "y")

        args = Namespace(id="123", force=False)
        result = _cmd_cleanup(temp_workspace, temp_registry, args)

        assert not ws_path.exists()
        assert result == 0

    def test_cleanup_without_force_cancelled(self, temp_workspace, temp_registry, monkeypatch):
        """Test cleanup without --force when user cancels."""
        ws_path = temp_workspace / "issue-123"

        # Simulate user saying "no"
        monkeypatch.setattr("builtins.input", lambda _: "n")

        args = Namespace(id="123", force=False)
        result = _cmd_cleanup(temp_workspace, temp_registry, args)

        assert ws_path.exists()
        # Aborting should return exit code 1
        assert result == 1

    def test_cleanup_nonexistent_workspace(self, temp_workspace, temp_registry, capsys):
        """Test cleanup for non-existent workspace."""
        args = Namespace(id="999", force=True)
        result = _cmd_cleanup(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        # Error messages go to stderr
        assert "No preserved workspace found" in captured.err
        assert result == 1

    def test_cleanup_clears_registry_intent(self, temp_workspace, capsys):
        """Test that cleanup clears retry intent in registry to prevent re-creation."""
        ws_path = temp_workspace / "issue-123"
        assert ws_path.exists()

        # Create a mock registry with retry intent
        mock_record = MagicMock()
        mock_record.intent = "retry"
        mock_record.workspace_path = str(ws_path)

        mock_registry = MagicMock()
        mock_registry.get_by_issue_ref.return_value = mock_record
        mock_registry.clear_intent.return_value = mock_record

        args = Namespace(id="123", force=True)

        # Mock _load_registry to return our mock registry
        with patch(
            "extensions.orchestrator.cli.workspace._load_registry", return_value=mock_registry
        ):
            result = _cmd_cleanup(temp_workspace, None, args)

        assert not ws_path.exists()
        assert result == 0
        # Verify registry was updated
        mock_registry.clear_intent.assert_called_once_with("123")
        assert mock_record.workspace_path is None
        mock_registry._save.assert_called_once()


class TestRunVerifyScript:
    """Tests for _cmd_verify function."""

    def test_run_verify_script_success(self, temp_workspace, temp_registry):
        """Test running verify.sh successfully."""
        ws_path = temp_workspace / "issue-123"
        orch_dir = ws_path / ".orchestrator_workspace"
        orch_dir.mkdir(exist_ok=True)
        verify_script = orch_dir / "verify.sh"
        verify_script.write_text("#!/bin/bash\necho 'Verification passed'\nexit 0")
        verify_script.chmod(0o755)

        args = Namespace(id="123")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"Verification passed")

            result = _cmd_verify(temp_workspace, temp_registry, args)

            assert result == 0
            mock_run.assert_called_once()

    def test_run_verify_script_failure(self, temp_workspace, temp_registry):
        """Test running verify.sh that fails."""
        ws_path = temp_workspace / "issue-123"
        orch_dir = ws_path / ".orchestrator_workspace"
        orch_dir.mkdir(exist_ok=True)
        verify_script = orch_dir / "verify.sh"
        verify_script.write_text("#!/bin/bash\necho 'Verification failed'\nexit 1")
        verify_script.chmod(0o755)

        args = Namespace(id="123")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"Verification failed")

            result = _cmd_verify(temp_workspace, temp_registry, args)

            assert result == 1

    def test_run_verify_script_not_found(self, temp_workspace, temp_registry, capsys):
        """Test running verify.sh when it doesn't exist."""
        args = Namespace(id="123")

        result = _cmd_verify(temp_workspace, temp_registry, args)

        captured = capsys.readouterr()
        # Error messages go to stderr
        assert "verify.sh not found" in captured.err or "verify.sh not found" in captured.out
        assert result == 1
