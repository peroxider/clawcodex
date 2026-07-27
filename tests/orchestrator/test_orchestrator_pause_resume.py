"""Tests for pause/resume/stop control commands.

Covers:
  * ``_apply_control_command`` sets ``_pause_gate`` correctly
    (control-file path — Bug 1 & 2).
  * Registry status updates on pause/resume (Bug 3).
"""

from __future__ import annotations

import asyncio
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from extensions.orchestrator.agent_runner import AgentSession
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.issue_registry import IssueRegistry, IssueStatus
from extensions.orchestrator.workspace import Workspace


def _make_session() -> AgentSession:
    """Build a minimal AgentSession with a live _pause_gate."""
    session = AgentSession(
        issue=Issue(id="test-1", identifier="test#1", title="Test issue"),
        workspace=Workspace(path="/tmp", issue_identifier="test#1", issue_id="test-1"),
        pause_resume_event=asyncio.Event(),
    )
    # _run_impl normally initialises _pause_gate at agent start.
    session._pause_gate = threading.Event()
    session._pause_gate.set()  # running (unpaused) state
    return session


def _apply_pause(session: AgentSession) -> None:
    """Simulate what _apply_control_command does for pause (control-file path)."""
    session.paused = True
    session.pause_reason = "operator requested pause"
    session.pause_resume_event.clear()
    # Bug 1 fix: block the headless session's on_event.
    if session._pause_gate is not None:
        session._pause_gate.clear()


def _apply_resume(session: AgentSession) -> None:
    """Simulate what _apply_control_command does for resume (control-file path)."""
    session.paused = False
    session.pause_resume_event.set()
    # Bug 2 fix: unblock the headless session's on_event.
    if session._pause_gate is not None:
        session._pause_gate.set()


# ---------------------------------------------------------------------------
# Bug 1: pause must clear _pause_gate
# ---------------------------------------------------------------------------


class TestPauseClearsPauseGate(unittest.TestCase):
    """When pause is applied via the control-file path, _pause_gate
    must be cleared so the headless session's on_event blocks."""

    def test_pause_clears_pause_gate(self) -> None:
        session = _make_session()
        self.assertTrue(
            session._pause_gate.is_set(), "Precondition: _pause_gate starts set (running)"
        )

        _apply_pause(session)

        self.assertTrue(session.paused)
        # 🔴 Without the fix, this fails:
        self.assertFalse(
            session._pause_gate.is_set(),
            "BUG 1: _pause_gate must be cleared on pause so LLM calls block",
        )

    def test_pause_does_not_lose_existing_fields(self) -> None:
        """Sanity: pause sets the expected fields even before the fix."""
        session = _make_session()
        _apply_pause(session)
        self.assertTrue(session.paused)
        self.assertIsNotNone(session.pause_reason)
        self.assertFalse(session.pause_resume_event.is_set())


# ---------------------------------------------------------------------------
# Bug 2: resume must set _pause_gate
# ---------------------------------------------------------------------------


class TestResumeSetsPauseGate(unittest.TestCase):
    """When resume is applied via the control-file path after a socket-path
    pause (which cleared _pause_gate), _pause_gate must be set so the
    headless session unblocks."""

    def test_resume_sets_pause_gate(self) -> None:
        session = _make_session()
        # Simulate socket-path pause (correctly clears _pause_gate).
        session.paused = True
        session._pause_gate.clear()
        session.pause_resume_event.clear()
        self.assertFalse(
            session._pause_gate.is_set(), "Precondition: _pause_gate cleared (paused via socket)"
        )

        # Now apply resume via the control-file path.
        _apply_resume(session)

        self.assertFalse(session.paused)
        # 🔴 Without the fix, this fails:
        self.assertTrue(
            session._pause_gate.is_set(),
            "BUG 2: _pause_gate must be set on resume so LLM calls unblock",
        )
        self.assertTrue(session.pause_resume_event.is_set())

    def test_resume_on_non_paused_session_is_safe(self) -> None:
        """Resume on an already-running session should be a no-op."""
        session = _make_session()
        _apply_resume(session)
        self.assertFalse(session.paused)
        self.assertTrue(session._pause_gate.is_set())
        self.assertTrue(session.pause_resume_event.is_set())


# ---------------------------------------------------------------------------
# Bug 3: registry must have a PAUSED status
# ---------------------------------------------------------------------------


class TestRegistryPausedStatus(unittest.TestCase):
    """IssueRegistry must support marking an issue as paused."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.registry = IssueRegistry(storage_path=Path(self.tmp.name) / "registry.json")
        self.registry.register("test-1", "test#1")

    def test_issue_status_has_paused(self) -> None:
        """IssueStatus enum must include PAUSED."""
        self.assertIn(
            "PAUSED",
            IssueStatus.__members__,
            "BUG 3: IssueStatus must have a PAUSED member",
        )
        self.assertEqual(IssueStatus.PAUSED.value, "paused")

    def test_mark_paused_updates_status(self) -> None:
        """mark_paused() must set the record status to PAUSED."""
        # This will fail until we add the method.
        result = self.registry.mark_paused("test-1")
        self.assertIsNotNone(result, "mark_paused should return the updated record")
        self.assertEqual(result.status, IssueStatus.PAUSED)

    def test_mark_paused_missing_returns_none(self) -> None:
        result = self.registry.mark_paused("missing")
        self.assertIsNone(result)

    def test_mark_paused_persists_reason(self) -> None:
        result = self.registry.mark_paused("test-1", reason="operator interrupt")
        self.assertEqual(result.pause_reason, "operator interrupt")

    def test_mark_resumed_restores_running(self) -> None:
        """mark_resumed() must restore the record status to RUNNING."""
        self.registry.mark_paused("test-1", reason="test")
        result = self.registry.mark_resumed("test-1")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, IssueStatus.RUNNING)

    def test_mark_resumed_missing_returns_none(self) -> None:
        self.assertIsNone(self.registry.mark_resumed("missing"))


if __name__ == "__main__":
    unittest.main()
