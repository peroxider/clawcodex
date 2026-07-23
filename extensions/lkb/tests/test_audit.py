"""Tests for F-137 Logical Kanban audit events and persistence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lkb import (
    AuditEvent,
    InMemoryAuditLog,
    LogicalKanbanService,
    ProposedChange,
    SessionFileAuditLog,
    TruthMaintenanceSystem,
    default_session_log_path,
    event_for_assumption_invalidated,
    event_for_commit,
    event_for_proposal,
    event_for_revalidation_requested,
    event_for_validation_run,
    get_audit_log,
)
from lkb.audit import _new_event_id
from lkb.fuzzy_types import Clarification
from lkb.types import CommitResult, Proposal, ValidationRun
try:
    from clawcodex_ext.tool_system.context import ToolContext
except ImportError:
    ToolContext = None  # standalone lkb
try:
    from src.tool_system.tools import TaskCreateTool, TaskUpdateTool
except ImportError:
    TaskCreateTool = TaskUpdateTool = None  # standalone lkb


def _set_lkb(monkeypatch, enabled: bool) -> None:
    try:
        from clawcodex_ext.feature_gate import get_registry

        monkeypatch.setitem(get_registry()._overrides, "logical_kanban", enabled)
    except (ImportError, AttributeError):
        pass  # standalone lkb: feature_gate not available


@pytest.fixture
def audit_log() -> InMemoryAuditLog:
    return InMemoryAuditLog()


def _make_proposal(
    kind: str = "transition_status",
    payload: dict[str, Any] | None = None,
    actor: str = "tester",
) -> Proposal:
    payload = payload or {"taskId": "T-001", "status": "in_progress"}
    return Proposal(
        proposal_id="P-test",
        change=ProposedChange(kind=kind, payload=payload, actor=actor),
        snapshot_hash="sha256:snap",
    )


def _make_validation(
    result: str = "pass",
    task_id: str | None = "T-001",
    issues: tuple[Any, ...] = (),
) -> ValidationRun:
    return ValidationRun(
        validation_run_id="V-test",
        proposal_id="P-test",
        task_id=task_id,
        result=result,
        issues=issues,
        created_at="2026-07-05T00:00:00+00:00",
        requested_by="tester",
    )


class TestAuditEventFactories:
    def test_event_for_proposal(self) -> None:
        proposal = _make_proposal()
        event = event_for_proposal(proposal, session_id="S-1")

        assert event.event_type == "lkb_proposal_created"
        assert event.actor == "tester"
        assert event.session_id == "S-1"
        assert event.proposal_id == "P-test"
        assert event.task_id == "T-001"
        assert event.decision is None
        assert event.payload["changeKind"] == "transition_status"

    def test_event_for_validation_run_pass(self) -> None:
        proposal = _make_proposal()
        validation = _make_validation(result="pass")
        event = event_for_validation_run(proposal, validation)

        assert event.event_type == "lkb_validation_run"
        assert event.validation_run_id == "V-test"
        assert event.decision == "accepted"
        assert event.payload["result"] == "pass"
        assert event.payload["issueCount"] == 0

    def test_event_for_validation_run_fail(self) -> None:
        proposal = _make_proposal()
        from lkb.types import ValidationIssue

        issue = ValidationIssue(
            code="blocked",
            message="blocked",
            rule="R-001",
            task_id="T-001",
        )
        validation = _make_validation(result="fail", issues=(issue,))
        event = event_for_validation_run(proposal, validation)

        assert event.decision == "denied"
        assert event.payload["issueCount"] == 1

    def test_event_for_commit(self) -> None:
        proposal = _make_proposal()
        validation = _make_validation(result="pass")
        commit = CommitResult(
            committed=True,
            proposal_id="P-test",
            validation_run_id="V-test",
        )
        event = event_for_commit(proposal, validation, commit)

        assert event.event_type == "lkb_commit"
        assert event.decision == "committed"
        assert event.payload["commit"]["committed"] is True

    def test_event_for_denial(self) -> None:
        proposal = _make_proposal()
        validation = _make_validation(result="fail")
        commit = CommitResult(
            committed=False,
            proposal_id="P-test",
            validation_run_id="V-test",
        )
        event = event_for_commit(proposal, validation, commit)

        assert event.event_type == "lkb_denial"
        assert event.decision == "denied"
        assert event.payload["denial"]["validationRunId"] == "V-test"

    def test_event_for_assumption_invalidated(self) -> None:
        event = event_for_assumption_invalidated(
            "H-001",
            "A-001",
            reason="user refuted",
            task_ids=("T-001", "T-002"),
            session_id="S-1",
            actor="user",
        )

        assert event.event_type == "lkb_assumption_invalidated"
        assert event.actor == "user"
        assert event.task_id == "T-001"
        assert event.payload["assumptionId"] == "H-001"
        assert event.payload["reason"] == "user refuted"

    def test_event_for_revalidation_requested(self) -> None:
        event = event_for_revalidation_requested(
            "T-001",
            triggered_by="assumption_clarified:H-001",
            previous_validation_run_id="V-old",
            session_id="S-1",
        )

        assert event.event_type == "lkb_revalidation_requested"
        assert event.task_id == "T-001"
        assert event.validation_run_id == "V-old"
        assert event.payload["triggeredBy"] == "assumption_clarified:H-001"


class TestInMemoryAuditLog:
    def test_append_and_query(self, audit_log: InMemoryAuditLog) -> None:
        event1 = event_for_proposal(_make_proposal())
        event2 = event_for_proposal(_make_proposal(payload={"taskId": "T-002"}))
        audit_log.append(event1)
        audit_log.append(event2)

        results = audit_log.query(task_id="T-001")
        assert len(results) == 1
        assert results[0].task_id == "T-001"

    def test_latest_for_task(self, audit_log: InMemoryAuditLog) -> None:
        proposal = _make_proposal()
        validation = _make_validation(result="fail")
        commit = CommitResult(
            committed=False,
            proposal_id="P-test",
            validation_run_id="V-test",
        )
        audit_log.append(event_for_commit(proposal, validation, commit))

        denial = audit_log.latest_for_task("T-001")
        assert denial is not None
        assert denial["validationRunId"] == "V-test"

    def test_query_returns_most_recent_first(self, audit_log: InMemoryAuditLog) -> None:
        for i in range(3):
            audit_log.append(event_for_proposal(_make_proposal(payload={"taskId": f"T-{i:03d}"})))

        results = audit_log.query(limit=2)
        assert [e.task_id for e in results] == ["T-002", "T-001"]


class TestSessionFileAuditLog:
    def test_appends_ndjson_line(self, tmp_path: Path) -> None:
        path = tmp_path / "events.ndjson"
        log = SessionFileAuditLog(path)
        event = event_for_proposal(_make_proposal(), session_id="S-1")
        log.append(event)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        import json

        parsed = json.loads(lines[0])
        assert parsed["eventType"] == "lkb_proposal_created"
        assert parsed["sessionId"] == "S-1"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "lkb" / "S-1" / "events.ndjson"
        log = SessionFileAuditLog(path)
        log.append(event_for_proposal(_make_proposal()))
        assert path.exists()

    def test_query_uses_memory_buffer(self, tmp_path: Path) -> None:
        path = tmp_path / "events.ndjson"
        log = SessionFileAuditLog(path)
        log.append(event_for_proposal(_make_proposal()))

        results = log.query(event_type="lkb_proposal_created")
        assert len(results) == 1


class TestGetAuditLog:
    def test_returns_runtime_audit_log_if_present(self, tmp_path: Path) -> None:
        from lkb import get_logical_kanban

        ctx = ToolContext(workspace_root=tmp_path)
        runtime = get_logical_kanban(ctx)
        custom = InMemoryAuditLog()
        runtime.audit_log = custom

        assert get_audit_log(ctx) is custom

    def test_creates_in_memory_log_without_session(self, tmp_path: Path) -> None:
        ctx = ToolContext(workspace_root=tmp_path)
        audit = get_audit_log(ctx)

        assert isinstance(audit, InMemoryAuditLog)
        assert ctx.logical_kanban.audit_log is audit

    def test_creates_session_file_log_with_session(self, monkeypatch, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)

        ctx = ToolContext(workspace_root=tmp_path, session_id="S-123")
        audit = get_audit_log(ctx)

        assert isinstance(audit, SessionFileAuditLog)
        assert audit.path == home / ".clawcodex" / "lkb" / "S-123" / "events.ndjson"


class TestServiceAuditIntegration:
    def test_propose_emits_event(self, tmp_path: Path) -> None:
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        service = LogicalKanbanService()
        change = ProposedChange(
            kind="create_task",
            payload={"taskId": "T-001"},
            actor="agent",
        )

        proposal = service.propose(change, ctx)

        events = get_audit_log(ctx).query(event_type="lkb_proposal_created")
        assert len(events) == 1
        assert events[0].proposal_id == proposal.proposal_id
        assert events[0].actor == "agent"

    def test_run_emits_proposal_validation_and_commit_events(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
            "id"
        ]

        TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

        audit = get_audit_log(ctx)
        assert len(audit.query(event_type="lkb_proposal_created")) == 2
        assert len(audit.query(event_type="lkb_validation_run")) == 2
        assert len(audit.query(event_type="lkb_commit")) == 2

    def test_run_emits_denial_event_for_blocked_transition(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
            "task"
        ]["id"]
        blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
            "task"
        ]["id"]
        TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

        TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)

        audit = get_audit_log(ctx)
        assert len(audit.query(event_type="lkb_denial")) == 1
        denial = audit.latest_for_task(blocked)
        assert denial is not None
        assert denial["result"] == "fail"

    def test_commit_persists_metadata_in_task(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        task_id = TaskCreateTool.call({"subject": "Task", "description": "D"}, ctx).output["task"][
            "id"
        ]

        TaskUpdateTool.call({"taskId": task_id, "status": "in_progress"}, ctx)

        lkb = ctx.tasks[task_id]["metadata"]["lkb"]
        assert lkb["last_decision"] == "committed"
        assert lkb["last_result"] == "pass"
        assert lkb["validation_run_id"].startswith("V-")
        assert lkb["proposal_id"].startswith("P-")

    def test_validation_run_can_be_inspected_after_denial(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        _set_lkb(monkeypatch, True)
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        blocker = TaskCreateTool.call({"subject": "Blocker", "description": "D1"}, ctx).output[
            "task"
        ]["id"]
        blocked = TaskCreateTool.call({"subject": "Blocked", "description": "D2"}, ctx).output[
            "task"
        ]["id"]
        TaskUpdateTool.call({"taskId": blocked, "addBlockedBy": [blocker]}, ctx)

        TaskUpdateTool.call({"taskId": blocked, "status": "in_progress"}, ctx)

        validation_events = get_audit_log(ctx).query(
            event_type="lkb_validation_run", task_id=blocked
        )
        denied_events = [e for e in validation_events if e.decision == "denied"]
        assert len(denied_events) == 1
        assert denied_events[0].payload["result"] == "fail"

        denial_events = get_audit_log(ctx).query(event_type="lkb_denial", task_id=blocked)
        assert len(denial_events) == 1
        validation = denial_events[0].payload["validation"]
        assert validation["result"] == "fail"
        assert validation["status"] == "denied"
        assert validation["taskId"] == blocked


class TestTmsInvalidationAudit:
    def test_invalidate_emits_assumption_invalidated_event(self, tmp_path: Path) -> None:
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        service = LogicalKanbanService()
        tms = service._tms(ctx)

        from lkb import Assumption

        assumption = Assumption(
            assumption_id="H-001",
            assertion_id="A-001",
            field="x",
            assumed_value="v",
            confidence=0.5,
            source="test",
        )
        tms.register_assertion("A-001", assumptions=(assumption,), task_ids=("T-001",))
        tms.invalidate_assumption("H-001", "user refuted")

        events = get_audit_log(ctx).query(event_type="lkb_assumption_invalidated")
        assert len(events) == 1
        assert events[0].payload["assumptionId"] == "H-001"
        assert events[0].payload["taskIds"] == ["T-001"]

    def test_clarify_emits_revalidation_event(self, tmp_path: Path) -> None:
        ctx = ToolContext(workspace_root=tmp_path, session_id="S-1")
        ctx.tasks["T-001"] = {"status": "pending"}
        service = LogicalKanbanService()
        tms = service._tms(ctx)

        from lkb import Assumption

        assumption = Assumption(
            assumption_id="H-001",
            assertion_id="A-001",
            field="x",
            assumed_value="v",
            confidence=0.5,
            source="test",
        )
        tms.register_assertion("A-001", assumptions=(assumption,), task_ids=("T-001",))
        tms.invalidate_assumption("H-001", "user refuted")

        service.clarify_assumption(
            ctx,
            "H-001",
            Clarification(assumption_id="H-001", action="confirm", new_value="v"),
        )

        events = get_audit_log(ctx).query(event_type="lkb_revalidation_requested")
        assert len(events) == 1
        assert events[0].task_id == "T-001"


def test_default_session_log_path_uses_session_id() -> None:
    path = default_session_log_path("S-1")
    assert path.name == "events.ndjson"
    assert path.parent.name == "S-1"


def test_default_session_log_path_returns_none_for_empty_session() -> None:
    assert default_session_log_path("") is None
    assert default_session_log_path(None) is None
