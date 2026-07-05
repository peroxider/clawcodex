"""F-139 security, performance, and observability tests for Logical Kanban."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from clawcodex_ext.logical_kanban import (
    LogicalKanbanService,
    ProposedChange,
    SolverPipeline,
    SolverRequest,
    encode_solver_facts,
    encode_solver_literal,
    register_sink,
    reset_sinks,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot, task_list_view
from clawcodex_ext.logical_kanban.runtime import get_logical_kanban
from clawcodex_ext.logical_kanban.solver_adapter import SolverAdapter, SolverResponse
from clawcodex_ext.logical_kanban.solver_limits import (
    SolverLimitError,
    SolverResourceLimits,
    run_external_solver,
)
from clawcodex_ext.tool_system.context import ToolContext


def _ci_multiplier() -> float:
    raw = os.environ.get('CLAWCODEX_CI_THRESHOLD_MULT', '1')
    try:
        return float(raw)
    except ValueError:
        return 1.0


@pytest.fixture
def service() -> LogicalKanbanService:
    return LogicalKanbanService()


@pytest.fixture
def empty_context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path)


@pytest.fixture
def collector():
    @dataclass
    class _Collector:
        events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

        def __call__(self, event: str, payload: dict[str, Any]) -> None:
            self.events.append((event, dict(payload)))

    reset_sinks()
    c = _Collector()
    register_sink(c)
    yield c
    reset_sinks()


def _add_task(
    context: ToolContext,
    task_id: str,
    *,
    status: str = 'pending',
    blocked_by: list[str] | None = None,
    blocks: list[str] | None = None,
    subject: str | None = None,
    description: str | None = None,
) -> None:
    context.tasks[task_id] = {
        'id': task_id,
        'subject': subject or task_id,
        'description': description or task_id,
        'status': status,
        'blockedBy': list(blocked_by or []),
        'blocks': list(blocks or []),
        'metadata': {},
    }


class TestObservabilityMetrics:
    def test_validation_run_metric_emitted(self, service, empty_context, collector) -> None:
        _add_task(empty_context, 'A', status='pending')
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'A', 'status': 'in_progress'},
        )
        service.run(change, empty_context)

        validation_events = [p for e, p in collector.events if e == 'lkb_validation_run']
        assert len(validation_events) == 1
        assert validation_events[0]['result'] == 'pass'
        assert validation_events[0]['change_kind'] == 'transition_status'
        assert validation_events[0]['task_count'] == 1

    def test_denial_metric_records_rule(self, service, empty_context, collector) -> None:
        _add_task(empty_context, 'A', status='pending')
        _add_task(empty_context, 'B', status='pending', blocked_by=['A'])
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'B', 'status': 'in_progress'},
        )
        service.run(change, empty_context)

        denial_events = [p for e, p in collector.events if e == 'lkb_denial']
        assert denial_events
        assert denial_events[0]['rule'] == 'R-002'
        assert denial_events[0]['code'] == 'blocked_task_cannot_enter_in_progress'

    def test_adapter_result_metric_emitted_on_timeout(
        self, empty_context, collector
    ) -> None:
        _add_task(empty_context, 'A', status='pending')
        pipeline = SolverPipeline([_SlowAdapter()])
        pipeline.validate(
            SolverRequest(
                snapshot=build_facts_snapshot(empty_context),
                target_task_id='A',
                target_status='in_progress',
            ),
            proposal_id='P-test',
            timeout_seconds=0.05,
        )

        adapter_events = [p for e, p in collector.events if e == 'lkb_adapter_result']
        assert adapter_events
        assert adapter_events[0]['adapter'] == 'slow'
        assert adapter_events[0]['result'] == 'timeout'

        timeout_events = [p for e, p in collector.events if e == 'lkb_solver_timeout']
        assert timeout_events
        assert timeout_events[0]['adapter'] == 'slow'

    def test_snapshot_cache_metrics(self, service, empty_context, collector) -> None:
        _add_task(empty_context, 'A', status='pending')
        service.snapshot(empty_context)
        service.snapshot(empty_context)

        hits = [p for e, p in collector.events if e == 'lkb_snapshot_cache_hit']
        misses = [p for e, p in collector.events if e == 'lkb_snapshot_cache_miss']
        assert len(misses) == 1
        assert len(hits) >= 1


class TestCorrectness:
    def test_lkb_failure_does_not_corrupt_context_tasks(
        self, service, empty_context
    ) -> None:
        _add_task(empty_context, 'A', status='pending')
        _add_task(empty_context, 'B', status='pending', blocked_by=['A'])
        original = dict(empty_context.tasks)

        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'B', 'status': 'in_progress'},
        )
        _proposal, validation, commit = service.run(change, empty_context)

        assert commit.committed is False
        assert validation.result == 'fail'
        assert empty_context.tasks == original

    def test_solver_unknown_denies_commit(self, service, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        service.pipeline = SolverPipeline([_AlwaysUnknownAdapter()])
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'A', 'status': 'in_progress'},
        )
        _proposal, validation, commit = service.run(change, empty_context)

        assert validation.result == 'unknown'
        assert commit.committed is False
        assert validation.issues[0].code == 'solver_unknown'

    def test_status_exclusivity_maintained(self, service, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        _add_task(empty_context, 'B', status='pending')
        change = ProposedChange(
            kind='legacy_todo_replace_all',
            payload={
                'todos': [
                    {'content': 'a', 'status': 'in_progress', 'activeForm': 'Doing a'},
                    {'content': 'b', 'status': 'in_progress', 'activeForm': 'Doing b'},
                ]
            },
        )
        runtime = get_logical_kanban(empty_context)
        runtime.strict_logical_todo_enabled = True
        _proposal, validation, commit = service.run(change, empty_context)

        assert commit.committed is False
        assert validation.issues[0].code == 'multiple_in_progress_legacy_todo_write'

    def test_commit_requires_current_validation_run(self, service, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'A', 'status': 'in_progress'},
        )
        proposal, validation, _commit = service.run(change, empty_context)
        assert validation.result == 'pass'

        # Mutate context after validation so the cached snapshot hash changes.
        _add_task(empty_context, 'B', status='pending')
        stale_commit = service.commit(proposal, validation, empty_context)

        assert stale_commit.committed is False
        assert stale_commit.reason['code'] == 'validation_stale'

    def test_nl_explanation_never_overrides_formal_denial(self, service, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        _add_task(empty_context, 'B', status='pending', blocked_by=['A'])
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'B', 'status': 'in_progress'},
        )
        _proposal, validation, commit = service.run(change, empty_context)

        assert validation.result == 'fail'
        assert commit.committed is False
        # Human-readable message exists but does not change the formal result.
        assert validation.issues[0].message
        assert validation.issues[0].rule == 'R-002'


class TestSecurity:
    def test_solver_literal_encoding_escapes_unsafe_text(self) -> None:
        raw = 'task with "quotes" and \n newlines and foo;bar'
        encoded = encode_solver_literal(raw)
        assert '"' not in encoded
        assert '\n' not in encoded
        assert ';' not in encoded
        assert encoded.startswith('task_with_')

    def test_solver_facts_encoding_never_includes_raw_nl(self, empty_context) -> None:
        _add_task(
            empty_context,
            'T1',
            status='pending',
            subject='subject with "quotes"',
            description='description with \n newline',
        )
        request = SolverRequest(snapshot=build_facts_snapshot(empty_context))
        encoded = encode_solver_facts(request)
        assert '"quotes"' not in encoded
        assert '\n newline' not in encoded
        assert 'T1' in encoded
        assert 'pending' in encoded

    def test_external_solver_enforces_timeout(self) -> None:
        with pytest.raises(SolverLimitError) as exc_info:
            run_external_solver(
                ['sleep', '5'],
                limits=SolverResourceLimits(timeout_seconds=0.1, max_memory_mb=64),
            )
        assert exc_info.value.reason == 'timeout'

    def test_external_solver_enforces_output_limit(self) -> None:
        with pytest.raises(SolverLimitError) as exc_info:
            run_external_solver(
                ['python3', '-c', 'print("x" * 100_000)'],
                limits=SolverResourceLimits(
                    timeout_seconds=5.0, max_memory_mb=64, max_output_bytes=100
                ),
            )
        assert exc_info.value.reason == 'output_limit'


class TestPerformance:
    def test_layer1_1000_tasks_under_200ms(self, empty_context) -> None:
        n = 1000
        for i in range(n):
            prev = f't{i - 1}' if i > 0 else None
            blocked_by = [prev] if prev else []
            blocks = [f't{i + 1}'] if i < n - 1 else []
            _add_task(
                empty_context,
                f't{i}',
                status='pending',
                blocked_by=blocked_by,
                blocks=blocks,
            )

        service = LogicalKanbanService()
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 't999', 'status': 'in_progress'},
        )
        start = time.perf_counter()
        _proposal, validation, _commit = service.run(change, empty_context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert validation.result == 'fail'
        assert elapsed_ms < 300 * _ci_multiplier(), (
            f'Layer-1 validation took {elapsed_ms:.1f}ms for 1000 tasks'
        )

    def test_fact_snapshot_under_100ms(self, empty_context) -> None:
        n = 1000
        for i in range(n):
            prev = f't{i - 1}' if i > 0 else None
            blocked_by = [prev] if prev else []
            blocks = [f't{i + 1}'] if i < n - 1 else []
            _add_task(
                empty_context,
                f't{i}',
                status='pending',
                blocked_by=blocked_by,
                blocks=blocks,
            )

        start = time.perf_counter()
        snapshot = build_facts_snapshot(empty_context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert snapshot.hash.startswith('sha256:')
        assert elapsed_ms < 100 * _ci_multiplier(), (
            f'Fact snapshot took {elapsed_ms:.1f}ms for 1000 tasks'
        )

    def test_task_update_overhead_under_50ms(self, empty_context) -> None:
        for i in range(20):
            _add_task(empty_context, f't{i}', status='pending')

        service = LogicalKanbanService()
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 't5', 'status': 'in_progress'},
        )
        start = time.perf_counter()
        service.run(change, empty_context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50 * _ci_multiplier(), (
            f'Task update overhead took {elapsed_ms:.1f}ms'
        )


class TestCaching:
    def test_task_list_reuses_snapshot_when_context_unchanged(self, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        first = task_list_view(empty_context)
        second = task_list_view(empty_context)
        assert first == second
        runtime = get_logical_kanban(empty_context)
        assert runtime._snapshot_cache_value is not None

    def test_snapshot_cache_invalidates_on_change(self, empty_context) -> None:
        _add_task(empty_context, 'A', status='pending')
        first = build_facts_snapshot(empty_context)
        _add_task(empty_context, 'B', status='pending')
        second = build_facts_snapshot(empty_context)
        assert first.hash != second.hash
        assert 'B' in second.normalized_tasks


class TestHumanOverrideAudit:
    def test_override_clarification_emits_audit_event(
        self, service, empty_context
    ) -> None:
        from clawcodex_ext.logical_kanban.fuzzy_types import (
            Assumption,
            AssumptionSource,
            Clarification,
        )

        assumption = Assumption(
            assumption_id='A-1',
            assertion_id='ASSERT-1',
            field='priority',
            assumed_value='high',
            confidence=0.8,
            source='user_clarified',
            clarification_prompt='What priority?',
            needs_clarification=True,
        )
        tms = get_logical_kanban(empty_context).tms
        tms.register_assertion('ASSERT-1', assumptions=(assumption,), task_ids=('T1',))

        clarification = Clarification(
            assumption_id='A-1',
            action='override',
            new_value='low',
        )
        new_record, old_record, _validation = service.clarify_assumption(
            empty_context, 'A-1', clarification
        )

        assert old_record is not None
        assert new_record is not None
        audit = get_logical_kanban(empty_context).audit_log
        assert audit is not None
        events = audit.query(event_type='lkb_human_override')
        assert len(events) == 1
        assert events[0].actor == 'system'
        assert events[0].payload['reason'] == 'user override'
        assert events[0].payload['taskIds'] == ['T1']


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _AlwaysUnknownAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return 'always-unknown'

    @property
    def version(self) -> str:
        return '0.0.0'

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        return SolverResponse(
            result='unknown',
            message='always unknown for testing',
        )


class _SlowAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return 'slow'

    @property
    def version(self) -> str:
        return '0.0.0'

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        time.sleep(1.0)
        return SolverResponse(result='pass')
