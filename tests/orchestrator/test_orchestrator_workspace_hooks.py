from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from extensions.orchestrator.agent_runner import AgentSession
from extensions.orchestrator.clarification_queue import ClarificationQueue
from extensions.orchestrator.config.schema import (
    AgentConfig,
    SandboxConfig,
    PollingConfig,
    TrackerConfig,
    WorkflowConfig,
    WorkspaceConfig,
)
from extensions.orchestrator.git_sync import (
    GitSyncPostCommitError,
    GitSyncResult,
    VerificationFailed,
)
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.issue_registry import IssueStatus
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.orchestrator.repo_tracker.client import RepositoryTrackerError
from extensions.orchestrator.tracker import TrackerAdapter
from extensions.orchestrator.tracker import PullRequestRef
from extensions.orchestrator.workspace import Workspace, WorkspaceHookError, WorkspaceManager


class _Tracker(TrackerAdapter):
    async def fetch_candidate_issues(self) -> list[Issue]:
        return []

    async def fetch_issue_states_by_ids(self, issue_ids: list[str]) -> dict[str, Issue]:
        return {}

    async def create_comment(self, issue_id: str, body: str) -> None:
        return None

    async def update_issue_state(self, issue_id: str, state: str) -> None:
        return None


class _RecordingTracker(_Tracker):
    def __init__(self) -> None:
        self.states: list[tuple[str, str]] = []

    async def update_issue_state(self, issue_id: str, state: str) -> None:
        self.states.append((issue_id, state))


class _HookWorkspaceManager(WorkspaceManager):
    def __init__(self) -> None:
        super().__init__(WorkspaceConfig(root=Path(tempfile.mkdtemp())))
        self.events: list[str] = []
        self.fail_before = False
        self.fail_after = False

    async def run_before_run_hook(self, workspace: Workspace, issue: Issue) -> None:
        self.events.append("before_run")
        if self.fail_before:
            raise WorkspaceHookError("before failed")

    async def run_after_run_hook(self, workspace: Workspace, issue: Issue) -> None:
        self.events.append("after_run")
        if self.fail_after:
            raise WorkspaceHookError("after failed")

    async def cleanup(self, issue: Issue, **kwargs: Any) -> None:
        self.events.append("cleanup")


class _Runner:
    def __init__(
        self,
        events: list[str],
        *,
        should_fail: bool = False,
        end_summary: str | None = None,
    ) -> None:
        self.max_turns = 2
        self._events = events
        self._should_fail = should_fail
        self._end_summary = end_summary

    async def run(self, session: AgentSession, workflow: WorkflowConfig, **kwargs) -> None:
        self._events.append("agent_run")
        if self._should_fail:
            raise RuntimeError("agent failed")
        session.status = "completed"
        session.session_end_reason = "task_complete"
        if self._end_summary is not None:
            session.session_end_summary = self._end_summary


class _PostCommitFailingSync:
    async def sync(self, session: AgentSession, *, mode: str = "default") -> None:
        result = GitSyncResult(
            branch_name="integration/f46",
            base_branch="main",
            commit_sha="abc123",
            committed=True,
            pending_review=True,
        )
        raise GitSyncPostCommitError(
            VerificationFailed("test verification failed", "pytest failed"),
            result,
        )


class _TrackerPullRequestFailingSync:
    async def sync(self, session: AgentSession, *, mode: str = "default") -> None:
        raise RepositoryTrackerError(
            'request_failed status=404 body={"error_code":404,'
            '"error_code_name":"UN_KNOW",'
            '"error_message":"Can not find the branch: main in project: perf-reference-ascend",'
            '"trace_id":"0fc549877113b9aea10e322792404fbe"}'
        )


class _SuccessfulReviewRetrySync:
    def __init__(self) -> None:
        self.modes: list[str] = []

    async def sync(self, session: AgentSession, *, mode: str = "default") -> GitSyncResult:
        self.modes.append(mode)
        return GitSyncResult(
            branch_name="clawcodex/issue-1",
            base_branch="main",
            commit_sha="def456",
            pull_request=PullRequestRef(
                number="7",
                url="https://gitcode.example/pulls/7",
            ),
            committed=True,
            pushed=True,
            pending_review=True,
        )


class _EmptyBranchSync:
    async def sync(self, session: AgentSession, *, mode: str = "default") -> GitSyncResult:
        return GitSyncResult(
            branch_name="clawcodex/issue-1",
            base_branch="main",
            committed=False,
            pushed=False,
            pending_review=False,
            session_end_reason="empty_branch_no_commits",
        )


class TestOrchestratorWorkspaceHooks(unittest.IsolatedAsyncioTestCase):
    def _workflow(self) -> WorkflowConfig:
        return WorkflowConfig(
            tracker=TrackerConfig(
                kind="linear",
                api_key="mock-key",
                project_slug="proj",
            ),
            polling=PollingConfig(interval_ms=1000),
            agent=AgentConfig(
                max_concurrent_agents=1,
                max_turns=2,
                provider="anthropic",
                permission_mode="dontAsk",
            ),
            sandbox=SandboxConfig(approval_policy="never"),
        )

    def _session(self) -> AgentSession:
        return AgentSession(
            issue=Issue(id="1", identifier="ISSUE-1", title="Test"),
            workspace=Workspace(
                path=Path(tempfile.mkdtemp()),
                issue_identifier="ISSUE-1",
                issue_id="1",
            ),
        )

    async def test_hooks_wrap_agent_run(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events)
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=_Tracker(),
            workspace=workspace,
            agent_runner=runner,
        )
        session = self._session()
        orchestrator._state.running[session.issue.id or "1"] = session

        await orchestrator._run_issue(session)

        self.assertEqual(
            workspace.events,
            ["before_run", "agent_run", "after_run", "cleanup"],
        )
        self.assertEqual(session.status, "completed")

    async def test_before_run_failure_skips_agent_and_after_run(self) -> None:
        workspace = _HookWorkspaceManager()
        workspace.fail_before = True
        runner = _Runner(workspace.events)
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=_Tracker(),
            workspace=workspace,
            agent_runner=runner,
        )
        session = self._session()
        orchestrator._state.running[session.issue.id or "1"] = session

        await orchestrator._run_issue(session)

        self.assertEqual(
            workspace.events,
            ["before_run", "cleanup"],
        )
        self.assertEqual(session.status, "before_run_failed")

    async def test_after_run_still_runs_when_agent_fails(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events, should_fail=True)
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=_Tracker(),
            workspace=workspace,
            agent_runner=runner,
        )
        session = self._session()
        orchestrator._state.running[session.issue.id or "1"] = session

        await orchestrator._run_issue(session)

        self.assertEqual(
            workspace.events,
            ["before_run", "agent_run", "after_run", "cleanup"],
        )
        self.assertEqual(session.status, "failed")

    async def test_post_commit_sync_failure_records_commit_before_failure(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events)
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=_Tracker(),
            workspace=workspace,
            agent_runner=runner,
        )
        orchestrator.git_sync = _PostCommitFailingSync()
        session = self._session()
        orchestrator._registry.register(
            issue_id=session.issue.id or "1",
            issue_identifier=session.issue.identifier or "ISSUE-1",
            branch_name="integration/f46",
            base_branch="main",
        )
        orchestrator._state.running[session.issue.id or "1"] = session

        await orchestrator._run_issue(session)

        record = orchestrator._registry.get(session.issue.id or "1")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.commit_sha, "abc123")
        self.assertEqual(record.branch_name, "integration/f46")
        self.assertEqual(record.status, IssueStatus.VERIFICATION_FAILED)
        self.assertEqual(record.verification_output, "pytest failed")

    async def test_git_sync_failure_overrides_stale_success_summary(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events, end_summary="issue no longer active")
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=_Tracker(),
            workspace=workspace,
            agent_runner=runner,
        )
        orchestrator.git_sync = _TrackerPullRequestFailingSync()
        delivered: list[tuple[Any, str]] = []
        orchestrator.im_event_deliver = lambda event, text: delivered.append((event, text))
        session = self._session()
        orchestrator._registry.register(
            issue_id=session.issue.id or "1",
            issue_identifier=session.issue.identifier or "ISSUE-1",
            status=IssueStatus.RUNNING,
        )
        orchestrator._state.running[session.issue.id or "1"] = session

        await orchestrator._run_issue(session)

        expected = (
            "request_failed status=404: "
            "Can not find the branch: main in project: perf-reference-ascend"
        )
        failed_texts = [
            text for event, text in delivered if getattr(event, "event_type", "") == "issue.failed"
        ]
        record = orchestrator._registry.get(session.issue.id or "1")

        self.assertEqual(session.status, "failed")
        self.assertEqual(session.session_end_reason, "failed")
        self.assertEqual(session.session_end_summary, expected)
        self.assertTrue(failed_texts)
        self.assertTrue(any(expected in text for text in failed_texts))
        self.assertTrue(all("issue no longer active" not in text for text in failed_texts))
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, IssueStatus.FAILED)
        self.assertEqual(record.verification_output, expected)
        self.assertEqual(record.last_hook_error, expected)
        self.assertEqual(record.session_end_reason, "failed")
        self.assertEqual(record.session_end_summary, expected)

    async def test_review_retry_updates_pr_and_returns_to_pending_review(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events)
        tracker = _RecordingTracker()
        workflow = self._workflow()
        workflow.agent.review_required = True
        orchestrator = Orchestrator(
            workflow=workflow,
            tracker=tracker,
            workspace=workspace,
            agent_runner=runner,
        )
        sync = _SuccessfulReviewRetrySync()
        orchestrator.git_sync = sync
        delivered: list[tuple[Any, str]] = []
        orchestrator.im_event_deliver = lambda event, text: delivered.append((event, text))
        session = self._session()
        session.run_kind = "review_retry"
        orchestrator._registry.register(
            issue_id="1",
            issue_identifier="ISSUE-1",
            branch_name="clawcodex/issue-1",
        )
        orchestrator._registry.mark_synced(
            "1",
            branch_name="clawcodex/issue-1",
            commit_sha="abc123",
            pr_number="7",
            pr_url="https://gitcode.example/pulls/7",
        )
        orchestrator._registry.mark_pending_review("1")
        orchestrator._clarification_queue = ClarificationQueue(
            session.workspace.path / "clarifications.json"
        )
        orchestrator._clarification_queue.inject_feedback(
            "1",
            "[Human Review Rejected] add the missing Chinese comment",
        )
        self.assertIsNotNone(orchestrator._clarification_queue.get_pending_feedback("1"))
        orchestrator._state.running["1"] = session

        await orchestrator._run_issue(session)

        record = orchestrator._registry.get("1")
        event_types = [getattr(event, "event_type", "") for event, _ in delivered]
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(sync.modes, ["followup"])
        self.assertEqual(record.status, IssueStatus.PENDING_REVIEW)
        self.assertEqual(record.pr_url, "https://gitcode.example/pulls/7")
        self.assertIn("1", orchestrator._state.pending_review)
        self.assertNotIn("1", orchestrator._state.completed)
        self.assertEqual(tracker.states, [("1", "pending_review")])
        self.assertIn("pr.updated", event_types)
        self.assertIn("pr.pending_review_gate", event_types)
        self.assertNotIn("issue.completed", event_types)
        self.assertIsNone(orchestrator._clarification_queue.get("1"))

    async def test_empty_branch_failure_is_not_finalized_as_completed(self) -> None:
        workspace = _HookWorkspaceManager()
        runner = _Runner(workspace.events)
        tracker = _RecordingTracker()
        orchestrator = Orchestrator(
            workflow=self._workflow(),
            tracker=tracker,
            workspace=workspace,
            agent_runner=runner,
        )
        orchestrator.git_sync = _EmptyBranchSync()
        delivered: list[tuple[Any, str]] = []
        orchestrator.im_event_deliver = lambda event, text: delivered.append((event, text))
        session = self._session()
        orchestrator._registry.register("1", "ISSUE-1")
        orchestrator._state.running["1"] = session

        await orchestrator._run_issue(session)

        record = orchestrator._registry.get("1")
        event_types = [getattr(event, "event_type", "") for event, _ in delivered]
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(session.status, "failed")
        self.assertEqual(record.status, IssueStatus.FAILED)
        self.assertNotIn("1", orchestrator._state.completed)
        self.assertEqual(tracker.states, [("1", "failed")])
        self.assertIn("issue.failed", event_types)
        self.assertNotIn("issue.completed", event_types)
