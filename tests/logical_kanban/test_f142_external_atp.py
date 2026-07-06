"""F-142 optional external ATP adapters."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from clawcodex_ext.logical_kanban import (
    InMemoryAuditLog,
    LogicalKanbanService,
    Mace4SolverAdapter,
    ProposedChange,
    SolverRequest,
    VampireSolverAdapter,
    extended_adapters,
    explain_validation_run,
)
from clawcodex_ext.logical_kanban.atp import parse_mace4_interpretation, parse_szs_status
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot
from clawcodex_ext.logical_kanban.runtime import get_logical_kanban
from clawcodex_ext.logical_kanban.types import Proposal, ValidationRun


def _ctx_with(tasks: dict[str, dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(tasks=tasks, todos=())


def _task(
    task_id: str,
    *,
    status: str = 'pending',
    blocked_by: list[str] | None = None,
) -> dict[str, Any]:
    return {
        'id': task_id,
        'subject': task_id,
        'description': '',
        'status': status,
        'blocks': [],
        'blockedBy': list(blocked_by or []),
        'metadata': {},
    }


def _req(ctx: SimpleNamespace, *, target: str = 'A', status: str = 'in_progress') -> SolverRequest:
    return SolverRequest(
        snapshot=build_facts_snapshot(ctx),
        target_task_id=target,
        target_status=status,
    )


def _force_external_available(monkeypatch, stdout: str):
    from clawcodex_ext.logical_kanban.atp import base

    base.ExternalAtpSolverAdapter._availability_cache.clear()
    base.ExternalAtpSolverAdapter._version_cache.clear()
    paths: list[str] = []
    tmpdirs: list[str] = []

    def fake_which(_binary: str) -> str:
        return 'mock-binary'

    def fake_run(command, *, input_text='', limits=None):
        if '--version' in command:
            return (0, 'mock-atp 1.0', '')
        program_path = command[-1]
        paths.append(program_path)
        tmpdirs.append(str(Path(program_path).parent))
        assert Path(program_path).exists()
        assert 'solver_syntax: tptp-fof' in Path(program_path).read_text(encoding='utf-8')
        return (0, stdout, '')

    monkeypatch.setattr(base.shutil, 'which', fake_which)
    monkeypatch.setattr(base, 'run_external_solver', fake_run)
    return paths, tmpdirs


def test_parse_szs_status_maps_standard_tokens() -> None:
    assert parse_szs_status('% SZS status Theorem') == 'pass'
    assert parse_szs_status('% SZS status CounterSatisfiable') == 'fail'
    assert parse_szs_status('% SZS status Satisfiable') == 'fail'
    assert parse_szs_status('% SZS status Timeout') == 'timeout'
    assert parse_szs_status('% SZS status Unknown') == 'error'


def test_vampire_theorem_populates_proof_and_cleans_tempdir(monkeypatch) -> None:
    paths, tmpdirs = _force_external_available(
        monkeypatch,
        '% SZS status Theorem\n% SZS output start\n[proof]\n% SZS output end\n',
    )
    ctx = _ctx_with({'A': _task('A')})
    response = VampireSolverAdapter().solve(_req(ctx))

    assert response.result == 'pass'
    assert response.proof_trace
    assert response.proof_trace[0]['rule'] == 'ATP-THEOREM'
    assert paths and tmpdirs
    assert not os.path.exists(tmpdirs[0])


def test_mace4_counterexample_is_parsed_and_attributed(monkeypatch) -> None:
    stdout = (
        '% SZS status Satisfiable\n'
        '% Interpretation:\n'
        'blocked("B") = true.\n'
        'do_proposal("B") = true.\n'
        'end_of_list.\n'
    )
    _force_external_available(monkeypatch, stdout)
    ctx = _ctx_with({'A': _task('A'), 'B': _task('B', blocked_by=['A'])})
    response = Mace4SolverAdapter().solve(_req(ctx, target='B'))

    assert response.result == 'fail'
    assert response.violated_rule == 'R-002'
    assert response.counterexample is not None
    assert response.counterexample['violatedRule'] == 'R-002'
    assert response.counterexample['tasks']['B']['blocked'] is True


def test_parse_mace4_interpretation_extracts_assignments() -> None:
    parsed = parse_mace4_interpretation('% Interpretation:\nblocked("T") = true.\n')
    assert parsed['assignments']['blocked(T)'] is True
    assert parsed['tasks']['T']['blocked'] is True


def test_absent_vampire_is_filtered_from_extended_adapters(monkeypatch) -> None:
    from clawcodex_ext.logical_kanban.atp import base

    base.ExternalAtpSolverAdapter._availability_cache.clear()
    monkeypatch.setattr(base.shutil, 'which', lambda _binary: None)
    names = {adapter.name for adapter in extended_adapters()}
    assert 'atp-vampire' not in names
    assert 'atp-tptp' in names


def test_validate_async_never_raises_and_emits_idempotent_enrichment(monkeypatch) -> None:
    _force_external_available(
        monkeypatch,
        '% SZS status Theorem\n% SZS output start\nproof-line\n% SZS output end\n',
    )
    ctx = _ctx_with({'A': _task('A')})
    runtime = get_logical_kanban(ctx)
    runtime.audit_log = InMemoryAuditLog()
    service = LogicalKanbanService()
    proposal = Proposal(
        proposal_id='P-async',
        change=ProposedChange(
            kind='transition_status',
            payload={'taskId': 'A', 'status': 'in_progress'},
            actor='tester',
        ),
        snapshot_hash=build_facts_snapshot(ctx).hash,
    )

    run = asyncio.run(
        asyncio.wait_for(
            service.validate_async(
                proposal,
                ctx,
                adapters=(VampireSolverAdapter(),),
                timeout_seconds=2.0,
            ),
            timeout=3.0,
        )
    )
    service._append_proof_enrichments(run, ctx)

    assert run.result == 'pass'
    assert runtime.audit_log is not None
    events = runtime.audit_log.query(event_type='lkb_proof_enrichment')
    assert len(events) == 1
    assert events[0].payload['adapter'] == 'atp-vampire'


def test_sync_taskupdate_latency_unchanged_when_external_atp_absent(monkeypatch) -> None:
    from clawcodex_ext.logical_kanban.atp import base

    base.ExternalAtpSolverAdapter._availability_cache.clear()
    monkeypatch.setattr(base.shutil, 'which', lambda _binary: None)
    ctx = _ctx_with({'A': _task('A')})
    service = LogicalKanbanService()
    service.pipeline.adapters = extended_adapters()
    change = ProposedChange(
        kind='transition_status',
        payload={'taskId': 'A', 'status': 'in_progress'},
    )

    start = time.perf_counter()
    _proposal, validation, _commit = service.run(change, ctx)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert validation.result == 'pass'
    assert elapsed_ms < 200


def test_explain_tags_llm_and_machine_proof_lines() -> None:
    validation = ValidationRun(
        validation_run_id='V-tag',
        proposal_id='P-tag',
        result='pass',
        proof_enrichment={
            'proofTrace': [{'rule': 'ATP-THEOREM', 'conclusion': 'proved'}],
            'llmAnnotations': ['human-facing note'],
        },
    )
    explanation = explain_validation_run(validation)

    assert explanation['proofEnrichmentSummary'] == [
        '[proof] ATP-THEOREM: proved',
        '[llm] human-facing note',
    ]
