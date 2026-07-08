"""F-120 Step 7: orchestrator daemon REBASE 分支 + agent reentry.

Covers:
  - _check_rebase_rate_limit:
      * under limit → True + incremented count
      * at limit + force=False → False + audit rebase_rejected
      * at limit + force=True → True + audit not rebase_rejected
  - _process_rebase_intent:
      * clean rebase → clear_conflict + commit_sha update
      * conflict rebase → mark_conflict with conflict_files
      * missing record → None (skipped)
      * missing workspace/branch → None (skipped)
  - _process_pending_rebase_conflicts:
      * empty when no record has has_conflict
      * launches agent_rebase when record has has_conflict
      * rate-limited records are skipped
  - _process_pr_conflict_scan:
      * disabled by default (no-op)
      * enabled but tracker returns no PRs → no-op
      * enabled + tracker reports has_conflicts → invokes _process_rebase_intent
      * GitCode fallback (status=None) is silently skipped
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from extensions.orchestrator.agent_runner import AgentSession
from extensions.orchestrator.config.schema import (
    PrConflictScanConfig,
    WorkflowConfig,
)
from extensions.orchestrator.git_sync import PRRebaseResult
from extensions.orchestrator.issue import Issue
from extensions.orchestrator.issue_registry import (
    IssueRegistry,
    IssueStatus,
)
from extensions.orchestrator.orchestrator import Orchestrator
from extensions.orchestrator.tracker import Intent, MergeableStatus, PullRequestRef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(
    *,
    tracker: Any,
    registry: IssueRegistry,
    workflow: WorkflowConfig | None = None,
) -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch.workflow = workflow or WorkflowConfig()
    orch.tracker = tracker
    orch.workspace = MagicMock()
    orch.agent_runner = MagicMock()
    orch.status_dashboard = MagicMock()
    orch._registry = registry
    orch._state = MagicMock()
    orch._state.running = {}
    orch._state.claimed = set()
    orch._state.max_concurrent_agents = 10
    orch._state.pr_conflict_scan_last_run = 0.0
    orch._log_audit_event = MagicMock()
    return orch


def _make_issue(issue_id: str = "7", branch_name: str | None = "feature/7") -> Issue:
    return Issue(
        id=issue_id,
        identifier=f"ISSUE-{issue_id}",
        title="F-120 E2E",
        branch_name=branch_name,
    )


_NO_WORKSPACE = object()


def _make_registry_record(
    tmp: Path,
    issue_id: str = "7",
    *,
    pr_number: int | None = 35,
    workspace_path: Any = _NO_WORKSPACE,
    branch_name: str | None = "feature/7",
    base_branch: str = "main",
    has_conflict: bool = False,
    rebase_attempt_count: int = 0,
    conflict_files: tuple[str, ...] = (),
) -> IssueRegistry:
    reg_path = tmp / "r.json"
    reg = IssueRegistry(reg_path)
    # Default to a synthetic temp workspace. Tests that want the
    # "no workspace" precondition pass ``workspace_path=None``
    # explicitly so we record None on the IssueRecord.
    if workspace_path is _NO_WORKSPACE:
        effective_workspace: str | None = str(tmp / "ws")
    else:
        effective_workspace = workspace_path
    reg.register(
        issue_id=issue_id,
        issue_identifier=f"ISSUE-{issue_id}",
        branch_name=branch_name,
        base_branch=base_branch,
        workspace_path=effective_workspace,
    )
    record = reg.get(issue_id)
    assert record is not None
    if effective_workspace is None:
        record.workspace_path = None
    record.pr_number = pr_number
    record.pr_url = f"https://example/pr/{pr_number}" if pr_number else None
    record.has_conflict = has_conflict
    record.conflict_files = conflict_files
    record.rebase_attempt_count = rebase_attempt_count
    reg._save()
    return reg


# ---------------------------------------------------------------------------
# _check_rebase_rate_limit
# ---------------------------------------------------------------------------


class TestCheckRebaseRateLimit(unittest.TestCase):
    def test_under_limit_allows_and_increments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = _make_registry_record(Path(tmp))
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)
            issue = _make_issue()
            self.assertTrue(orch._check_rebase_rate_limit(issue))
            reloaded = IssueRegistry(Path(tmp) / "r.json")
            self.assertEqual(reloaded.get("7").rebase_attempt_count, 1)

    def test_at_limit_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = _make_registry_record(Path(tmp), rebase_attempt_count=3)
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)
            issue = _make_issue()
            # Default max_rebase_attempts_per_issue = 3.
            self.assertFalse(orch._check_rebase_rate_limit(issue))
            orch._log_audit_event.assert_called_once()
            call_kwargs = orch._log_audit_event.call_args.kwargs
            self.assertEqual(call_kwargs["event"], "rebase_rejected")

    def test_at_limit_with_force_bypasses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = _make_registry_record(Path(tmp), rebase_attempt_count=3)
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)
            issue = _make_issue()
            self.assertTrue(orch._check_rebase_rate_limit(issue, force=True))
            # rebase_rejected NOT called when force bypasses.
            orch._log_audit_event.assert_not_called()


# ---------------------------------------------------------------------------
# _process_rebase_intent
# ---------------------------------------------------------------------------


class TestProcessRebaseIntent(unittest.IsolatedAsyncioTestCase):
    async def test_clean_rebase_clears_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(
                tmp_path,
                has_conflict=True,
                conflict_files=("src/a.py",),
            )
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)

            clean_result = PRRebaseResult(
                rebased=True,
                has_conflict=False,
                conflict_files=(),
                new_head_sha="abcdef0123456789",
                pushed=True,
                push_method="force_with_lease",
                workspace_clean=True,
            )
            with patch(
                "extensions.orchestrator.orchestrator.rebase_for_pr",
                return_value=clean_result,
            ) as mocked:
                result = await orch._process_rebase_intent(_make_issue())
            self.assertIs(result, clean_result)
            mocked.assert_called_once()
            reloaded = IssueRegistry(tmp_path / "r.json")
            record = reloaded.get("7")
            assert record is not None
            self.assertFalse(record.has_conflict)
            self.assertEqual(list(record.conflict_files), [])
            self.assertEqual(record.commit_sha, "abcdef0123456789")

    async def test_conflict_rebase_marks_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, has_conflict=False)
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)

            conflict_result = PRRebaseResult(
                rebased=False,
                has_conflict=True,
                conflict_files=("src/plugins/x.py", "src/plugins/y.py"),
                workspace_clean=False,
            )
            with patch(
                "extensions.orchestrator.orchestrator.rebase_for_pr",
                return_value=conflict_result,
            ):
                result = await orch._process_rebase_intent(_make_issue())
            assert result is not None
            self.assertTrue(result.has_conflict)
            reloaded = IssueRegistry(tmp_path / "r.json")
            record = reloaded.get("7")
            assert record is not None
            self.assertTrue(record.has_conflict)
            self.assertEqual(
                tuple(record.conflict_files),
                ("src/plugins/x.py", "src/plugins/y.py"),
            )
            orch._log_audit_event.assert_called()
            # Audit event is "rebase_conflict".
            event_names = [
                call.kwargs.get("event") for call in orch._log_audit_event.call_args_list
            ]
            self.assertIn("rebase_conflict", event_names)

    async def test_no_record_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = IssueRegistry(Path(tmp) / "r.json")
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)
            result = await orch._process_rebase_intent(_make_issue("999"))
            self.assertIsNone(result)

    async def test_missing_workspace_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, workspace_path=None)
            orch = _make_orchestrator(tracker=MagicMock(), registry=reg)
            result = await orch._process_rebase_intent(_make_issue())
            self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _process_pending_rebase_conflicts
# ---------------------------------------------------------------------------


class TestProcessPendingRebaseConflicts(unittest.IsolatedAsyncioTestCase):
    async def test_no_conflicts_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, has_conflict=False)
            tracker = MagicMock()
            orch = _make_orchestrator(tracker=tracker, registry=reg)
            orch.workspace.create_for_issue = AsyncMock()
            orch._launch_rebase_resolution = AsyncMock()
            await orch._process_pending_rebase_conflicts()
            orch._launch_rebase_resolution.assert_not_called()

    async def test_conflict_launches_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(
                tmp_path,
                has_conflict=True,
                conflict_files=("src/x.py",),
            )
            tracker = MagicMock()
            issue = _make_issue()
            tracker.fetch_issue_states_by_ids = AsyncMock(return_value={"7": issue})
            orch = _make_orchestrator(tracker=tracker, registry=reg)
            orch.workspace.create_for_issue = AsyncMock(
                return_value=MagicMock(path=tmp_path / "ws")
            )
            orch.workspace.current_head = AsyncMock(return_value="abc123")
            orch._launch_rebase_resolution = AsyncMock()
            orch._state.max_concurrent_agents = 10
            orch._state.running = {}
            await orch._process_pending_rebase_conflicts()
            orch._launch_rebase_resolution.assert_awaited_once()
            # First arg is the Issue.
            self.assertEqual(orch._launch_rebase_resolution.await_args.args[0].id, "7")

    async def test_rate_limited_records_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(
                tmp_path,
                has_conflict=True,
                rebase_attempt_count=3,  # at limit
            )
            tracker = MagicMock()
            issue = _make_issue()
            tracker.fetch_issue_states_by_ids = AsyncMock(return_value={"7": issue})
            orch = _make_orchestrator(tracker=tracker, registry=reg)
            orch.workspace.create_for_issue = AsyncMock()
            orch._launch_rebase_resolution = AsyncMock()
            orch._state.max_concurrent_agents = 10
            orch._state.running = {}
            await orch._process_pending_rebase_conflicts()
            orch._launch_rebase_resolution.assert_not_called()


# ---------------------------------------------------------------------------
# _process_pr_conflict_scan
# ---------------------------------------------------------------------------


class TestProcessPrConflictScan(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path)
            tracker = MagicMock()
            tracker.fetch_pull_request_mergeable = AsyncMock()
            orch = _make_orchestrator(tracker=tracker, registry=reg)
            await orch._process_pr_conflict_scan()
            tracker.fetch_pull_request_mergeable.assert_not_called()

    async def test_enabled_no_prs_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, pr_number=None)
            workflow = WorkflowConfig()
            workflow.pr_conflict_scan = PrConflictScanConfig(enabled=True)
            tracker = MagicMock()
            tracker.fetch_pull_request_mergeable = AsyncMock()
            orch = _make_orchestrator(tracker=tracker, registry=reg, workflow=workflow)
            await orch._process_pr_conflict_scan()
            tracker.fetch_pull_request_mergeable.assert_not_called()

    async def test_enabled_with_conflict_dispatches_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, has_conflict=False)
            # Pin pr_state so the scan does not skip the record on
            # the state filter.
            reg.get("7").pr_state = "open"
            reg._save()
            workflow = WorkflowConfig()
            workflow.pr_conflict_scan = PrConflictScanConfig(enabled=True)
            tracker = MagicMock()
            conflict_status = MergeableStatus(
                mergeable=False,
                mergeable_state="dirty",
                has_conflicts=True,
                behind_by=2,
            )
            tracker.fetch_pull_request_mergeable = AsyncMock(return_value=conflict_status)
            issue = _make_issue()
            tracker.fetch_issue_states_by_ids = AsyncMock(return_value={"7": issue})
            orch = _make_orchestrator(tracker=tracker, registry=reg, workflow=workflow)
            orch._process_rebase_intent = AsyncMock()
            await orch._process_pr_conflict_scan()
            tracker.fetch_pull_request_mergeable.assert_awaited_once()
            orch._process_rebase_intent.assert_awaited_once()

    async def test_gitcode_fallback_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reg = _make_registry_record(tmp_path, has_conflict=False)
            workflow = WorkflowConfig()
            workflow.pr_conflict_scan = PrConflictScanConfig(enabled=True)
            tracker = MagicMock()
            tracker.fetch_pull_request_mergeable = AsyncMock(return_value=None)
            orch = _make_orchestrator(tracker=tracker, registry=reg, workflow=workflow)
            orch._process_rebase_intent = AsyncMock()
            await orch._process_pr_conflict_scan()
            # None from tracker → daemon scan is a no-op on GitCode.
            orch._process_rebase_intent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
