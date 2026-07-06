"""Tests for the F-138 Layer-5 ATP/TPTP solver adapter.

The ATP/TPTP adapter is backed by an in-process refutation prover at
``clawcodex_ext/logical_kanban/solver_atp.py``. Because the prover has
no external binary requirement these tests run unconditionally — no
``pytest.importorskip`` guard is needed.

The tests mirror the Z3 / Clingo suites: availability / version
checks, decision-matrix coverage, query guards, pipeline integration,
F-139 sanitisation, and an audit check that verifies the TPTP program
emitted by :meth:`AtpTptpSolverAdapter.last_tptp_program` is well-formed
enough to be piped to ``vampire`` / ``eprover`` if either were on
``PATH``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from clawcodex_ext.logical_kanban import (  # noqa: E402
    AtpTptpSolverAdapter,
    Layer1SolverAdapter,
    LogicalKanbanService,
    ProposedChange,
    SolverAdapter,
    SolverPipeline,
    SolverRequest,
    SolverResponse,
    extended_adapters,
)
from clawcodex_ext.logical_kanban.context_adapter import build_facts_snapshot  # noqa: E402
from clawcodex_ext.logical_kanban.solver_adapter import (  # noqa: E402
    encode_solver_literal,
)
from clawcodex_ext.logical_kanban.solver_atp import (  # noqa: E402
    Clause,
    Literal,
    emit_tptp_program,
    pred,
    prove_lkb_request,
    saturate,
    task_constants,
)
from clawcodex_ext.logical_kanban.types import FactsSnapshot  # noqa: E402


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ctx_with(tasks: dict[str, dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(tasks=tasks, todos=())


def _snapshot(context: SimpleNamespace) -> FactsSnapshot:
    return build_facts_snapshot(context)


def _req(snapshot, *, target=None, status=None, strict=False, proof=None):
    return SolverRequest(
        snapshot=snapshot,
        target_task_id=target,
        target_status=status,
        strict_acceptance=strict,
        acceptance_proof_present=proof,
    )


def _task(
    task_id: str,
    *,
    status: str = 'pending',
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    subject: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        'id': task_id,
        'subject': subject if subject is not None else task_id,
        'description': description if description is not None else '',
        'status': status,
        'blocks': list(blocks or []),
        'blockedBy': list(blocked_by or []),
        'metadata': dict(metadata or {}),
    }
    return body


# ---------------------------------------------------------------------------
# Prover unit tests (in isolation, no adapter plumbing)
# ---------------------------------------------------------------------------


class TestSaturate:
    def test_empty_set_is_sat(self) -> None:
        derived_false, count = saturate([])
        assert derived_false is False
        assert count == 0

    def test_unit_fact_does_not_derive_false(self) -> None:
        c = Clause(frozenset({pred('p', 'a', positive=True)}))
        derived_false, _ = saturate([c])
        assert derived_false is False

    def test_complementary_units_derive_false(self) -> None:
        p = Clause(frozenset({pred('p', 'a', positive=True)}))
        np = Clause(frozenset({pred('p', 'a', positive=False)}))
        derived_false, _ = saturate([p, np])
        assert derived_false is True

    def test_tautology_is_dropped(self) -> None:
        # p(a) ∨ ¬p(a) is a tautology — never contributes to refutation.
        c = Clause(frozenset({
            pred('p', 'a', positive=True),
            pred('p', 'a', positive=False),
        }))
        derived_false, count = saturate([c])
        assert derived_false is False
        assert count == 0  # tautology dropped before saturation

    def test_subsumption(self) -> None:
        # The shorter clause subsumes the longer one; the longer clause
        # should be discarded as redundant before resolution starts.
        short = Clause(frozenset({pred('p', 'a', positive=True)}))
        long = Clause(frozenset({
            pred('p', 'a', positive=True),
            pred('q', 'b', positive=False),
        }))
        assert short.subsumes(long)
        assert not long.subsumes(short)


class TestProverEndToEnd:
    """Drive :func:`prove_lkb_request` directly with the same payloads
    the adapter would compute."""

    def test_ready_task_passes(self) -> None:
        v, m = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=False, proposal_target='A',
            proposal_status='in_progress', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'pass'
        assert m['clause_count'] > 0

    def test_blocked_fails(self) -> None:
        v, m = prove_lkb_request(
            constants=('A', 'B'), blocked_ids=frozenset({'B'}),
            cycle_ids=frozenset(), has_proof_ids=frozenset(),
            completed_ids=frozenset(), strict_acceptance=False,
            proposal_target='B', proposal_status='in_progress',
            snapshot_task_ids=frozenset({'A', 'B'}),
        )
        assert v == 'fail'
        assert m['reason'] == 'refutation'

    def test_cycle_fails(self) -> None:
        v, _ = prove_lkb_request(
            constants=('A', 'B'), blocked_ids=frozenset({'A', 'B'}),
            cycle_ids=frozenset({'A', 'B'}), has_proof_ids=frozenset(),
            completed_ids=frozenset(), strict_acceptance=False,
            proposal_target='A', proposal_status='in_progress',
            snapshot_task_ids=frozenset({'A', 'B'}),
        )
        assert v == 'fail'

    def test_strict_no_proof_fails(self) -> None:
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=True, proposal_target='A',
            proposal_status='completed', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'fail'

    def test_strict_with_proof_passes(self) -> None:
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset({'A'}), completed_ids=frozenset(),
            strict_acceptance=True, proposal_target='A',
            proposal_status='completed', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'pass'

    def test_unknown_target_fails(self) -> None:
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=False, proposal_target='Z',
            proposal_status='pending', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'fail'

    def test_reopen_passes(self) -> None:
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset({'A'}),
            strict_acceptance=False, proposal_target='A',
            proposal_status='pending', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'pass'

    def test_delete_status_passes(self) -> None:
        # ``deleted`` is a structural change with no invariant — the
        # prover never sees a proposal atom and reports SAT.
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=False, proposal_target='A',
            proposal_status='deleted', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'pass'

    def test_unsupported_status_passes(self) -> None:
        # Unknown statuses (e.g. ``archived``) are silently dropped, so
        # the prover reports SAT.
        v, _ = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=False, proposal_target='A',
            proposal_status='archived', snapshot_task_ids=frozenset({'A'}),
        )
        assert v == 'pass'

    def test_saturation_cap_returns_unknown(self) -> None:
        # Force the saturation cap to be tiny to simulate an inconclusive
        # outcome. The prover should report ``unknown`` rather than
        # silently claiming pass or fail.
        v, m = prove_lkb_request(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), completed_ids=frozenset(),
            strict_acceptance=False, proposal_target='A',
            proposal_status='in_progress',
            snapshot_task_ids=frozenset({'A'}),
            max_new_clauses=0,
        )
        assert v == 'unknown'
        assert m['reason'] == 'saturation_cap'


class TestTaskConstants:
    def test_sorted_unique(self) -> None:
        assert task_constants({'b', 'a', 'a', 'c'}) == ('a', 'b', 'c')

    def test_empty(self) -> None:
        assert task_constants([]) == ()


# ---------------------------------------------------------------------------
# TPTP emitter
# ---------------------------------------------------------------------------


class TestTptpEmitter:
    def test_emits_well_formed_fof(self) -> None:
        program = emit_tptp_program(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), strict_acceptance=False,
            proposal_target='A', proposal_status='in_progress',
        )
        # Each non-comment line is a TPTP ``fof(name, role, formula).``
        for line in program.splitlines():
            if not line or line.startswith('%'):
                continue
            assert line.startswith('fof(')
            assert line.rstrip().endswith(').')
            # Role must be ``axiom`` or ``conjecture``.
            inner = line[len('fof('):-len(').')]
            parts = inner.split(',', 2)
            assert parts[1].strip() in ('axiom', 'conjecture')

    def test_conjecture_is_the_proposal_atom(self) -> None:
        program = emit_tptp_program(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), strict_acceptance=True,
            proposal_target='A', proposal_status='completed',
        )
        assert 'conjecture' in program
        assert 'complete_proposal' in program

    def test_strict_acceptance_emits_r005_axiom(self) -> None:
        program = emit_tptp_program(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), strict_acceptance=True,
            proposal_target='A', proposal_status='completed',
        )
        # R-005 is only emitted in strict mode.
        assert 'r005_' in program

    def test_no_strict_acceptance_skips_r005(self) -> None:
        program = emit_tptp_program(
            constants=('A',), blocked_ids=frozenset(), cycle_ids=frozenset(),
            has_proof_ids=frozenset(), strict_acceptance=False,
            proposal_target='A', proposal_status='completed',
        )
        assert 'r005_' not in program


# ---------------------------------------------------------------------------
# Adapter surface (smoke / availability / decision matrix)
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_always_available(self) -> None:
        # No external binary is required; the prover is in-process.
        assert AtpTptpSolverAdapter().available() is True

    def test_version_is_stable(self) -> None:
        adapter = AtpTptpSolverAdapter()
        assert adapter.version == 'lkb-atp/0.1.0'

    def test_engine_name(self) -> None:
        assert AtpTptpSolverAdapter().name == 'atp-tptp'


class TestExtendedAdapters:
    def test_extended_adapters_keeps_layer1_first(self) -> None:
        adapters = extended_adapters()
        assert adapters[0].name == 'layer1-python'

    def test_extended_adapters_includes_atp(self) -> None:
        names = {a.name for a in extended_adapters()}
        assert 'atp-tptp' in names


# ---------------------------------------------------------------------------
# Truth-table / decision coverage
# ---------------------------------------------------------------------------


class TestDecisionMatrix:
    def test_ready_task_passes(self) -> None:
        ctx = _ctx_with({'A': _task('A')})
        response = AtpTptpSolverAdapter().solve(
            _req(_snapshot(ctx), target='A', status='in_progress')
        )
        assert response.result == 'pass'
        assert response.proof_trace
        assert response.proof_trace[0]['rule'] == 'ATP-SAT'

    def test_blocked_task_fails_with_r002(self) -> None:
        ctx = _ctx_with(
            {'A': _task('A'), 'B': _task('B', blocked_by=['A'])}
        )
        snap = _snapshot(ctx)
        response = AtpTptpSolverAdapter().solve(
            _req(snap, target='B', status='in_progress')
        )
        assert response.result == 'fail'
        assert response.violated_rule == 'R-002'
        assert 'A' in response.message

    def test_cycle_task_prefers_r006(self) -> None:
        ctx = _ctx_with(
            {
                'A': _task('A', blocks=['B']),
                'B': _task('B', blocks=['A'], blocked_by=['A']),
            }
        )
        snap = _snapshot(ctx)
        assert 'A' in snap.cycle_task_ids
        response = AtpTptpSolverAdapter().solve(
            _req(snap, target='A', status='in_progress')
        )
        assert response.result == 'fail'
        assert response.violated_rule == 'R-006'

    def test_strict_acceptance_requires_proof(self) -> None:
        ctx = _ctx_with(
            {
                'A': _task(
                    'A',
                    status='in_progress',
                    metadata={'lkb': {'strict_acceptance': True}},
                ),
            }
        )
        snap = _snapshot(ctx)
        response = AtpTptpSolverAdapter().solve(
            _req(snap, target='A', status='completed', strict=True, proof=False)
        )
        assert response.result == 'fail'
        assert response.violated_rule == 'R-005'

    def test_strict_acceptance_with_proof_passes(self) -> None:
        ctx = _ctx_with(
            {
                'A': _task(
                    'A',
                    status='in_progress',
                    metadata={
                        'lkb': {
                            'strict_acceptance': True,
                            'acceptance_proof': 'hash-of-evidence',
                        }
                    },
                ),
            }
        )
        snap = _snapshot(ctx)
        response = AtpTptpSolverAdapter().solve(
            _req(snap, target='A', status='completed', strict=True, proof=True)
        )
        assert response.result == 'pass'

    def test_completed_to_pending_reopens(self) -> None:
        ctx = _ctx_with({'A': _task('A', status='completed')})
        response = AtpTptpSolverAdapter().solve(
            _req(_snapshot(ctx), target='A', status='pending')
        )
        assert response.result == 'pass'

    def test_completed_to_in_progress_reopens(self) -> None:
        ctx = _ctx_with({'A': _task('A', status='completed')})
        response = AtpTptpSolverAdapter().solve(
            _req(_snapshot(ctx), target='A', status='in_progress')
        )
        assert response.result == 'pass'


# ---------------------------------------------------------------------------
# Query completeness guards
# ---------------------------------------------------------------------------


class TestQueryGuards:
    def test_unknown_target_id_denied(self) -> None:
        ctx = _ctx_with({'A': _task('A')})
        response = AtpTptpSolverAdapter().solve(
            _req(_snapshot(ctx), target='Z', status='pending')
        )
        assert response.result == 'fail'
        assert response.violated_rule == 'LKB-TRANSITION-001'


# ---------------------------------------------------------------------------
# Aggregation with the pipeline
# ---------------------------------------------------------------------------


class _AlwaysPassAdapter(SolverAdapter):
    @property
    def name(self) -> str:
        return 'always-pass'

    @property
    def version(self) -> str:
        return '0.0.0'

    def available(self) -> bool:
        return True

    def solve(
        self, request: SolverRequest, *, timeout_seconds: float = 30.0
    ) -> SolverResponse:
        return SolverResponse(result='pass')


class TestPipelineIntegration:
    def test_layer1_plus_atp_agrees_on_ready(self) -> None:
        ctx = _ctx_with({'A': _task('A')})
        pipeline = SolverPipeline([Layer1SolverAdapter(), AtpTptpSolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target='A', status='in_progress'),
            proposal_id='P-ready',
        )
        assert run.result == 'pass'
        engines = {r['adapter'] for r in run.solver_results}
        assert engines == {'layer1-python', 'atp-tptp'}

    def test_any_fail_means_overall_fail(self) -> None:
        ctx = _ctx_with(
            {'A': _task('A'), 'B': _task('B', blocked_by=['A'])}
        )
        pipeline = SolverPipeline([Layer1SolverAdapter(), AtpTptpSolverAdapter()])
        run = pipeline.validate(
            _req(_snapshot(ctx), target='B', status='in_progress'),
            proposal_id='P-block',
        )
        assert run.result == 'fail'
        assert all(r['result'] == 'fail' for r in run.solver_results)

    def test_strict_acceptance_blocked_by_atp_only(self) -> None:
        ctx = _ctx_with(
            {
                'A': _task(
                    'A',
                    status='in_progress',
                    metadata={'lkb': {'strict_acceptance': True}},
                ),
            }
        )
        pipeline = SolverPipeline([AtpTptpSolverAdapter()])
        run = pipeline.validate(
            _req(
                _snapshot(ctx),
                target='A',
                status='completed',
                strict=True,
                proof=False,
            ),
            proposal_id='P-strict',
        )
        assert run.result == 'fail'
        assert run.engine == 'atp-tptp'
        atp_entry = next(r for r in run.solver_results if r['adapter'] == 'atp-tptp')
        assert atp_entry['result'] == 'fail'
        assert atp_entry['violatedRule'] == 'R-005'


# ---------------------------------------------------------------------------
# Service-level smoke test
# ---------------------------------------------------------------------------


class TestServiceWithAtpPipeline:
    def test_service_can_swap_in_atp_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _ctx_with(
            {'A': _task('A'), 'B': _task('B', blocked_by=['A'])}
        )
        service = LogicalKanbanService()
        service.pipeline = SolverPipeline(
            [Layer1SolverAdapter(), AtpTptpSolverAdapter()]
        )
        snapshot = _snapshot(ctx)
        from clawcodex_ext.logical_kanban.runtime import get_logical_kanban

        runtime = get_logical_kanban(ctx)
        runtime._snapshot_cache_key = None
        change = ProposedChange(
            kind='transition_status',
            payload={'taskId': 'B', 'status': 'in_progress'},
        )
        _proposal, validation, commit = service.run(change, ctx)
        assert validation.result == 'fail'
        assert commit.committed is False
        adapter_names = {r['adapter'] for r in validation.solver_results}
        assert {'layer1-python', 'atp-tptp'}.issubset(adapter_names)


# ---------------------------------------------------------------------------
# F-139 sanitisation
# ---------------------------------------------------------------------------


class TestSecuritySanitisation:
    def test_encode_solver_literal_rejects_unsafe_chars(self) -> None:
        escaped = encode_solver_literal('<script>alert(1)</script>')
        assert '<' not in escaped and '>' not in escaped

    def test_hostile_subject_does_not_crash(self) -> None:
        # Adversarial subject/description. The prover routes task ids
        # through :func:`encode_solver_literal`; the TPTP emitter wraps
        # the result in double quotes so it remains a syntactically
        # valid distinct-object atom.
        ctx = _ctx_with(
            {
                'A': _task(
                    'A',
                    subject='"; (assert (not blocked)).',
                    description='\\x00\\n',
                ),
            }
        )
        response = AtpTptpSolverAdapter().solve(
            _req(_snapshot(ctx), target='A', status='in_progress')
        )
        assert response.result == 'pass'


# ---------------------------------------------------------------------------
# TPTP audit surface
# ---------------------------------------------------------------------------


class TestTptpAudit:
    def test_last_tptp_program_is_well_formed(self) -> None:
        adapter = AtpTptpSolverAdapter()
        ctx = _ctx_with({'A': _task('A')})
        adapter.solve(
            _req(_snapshot(ctx), target='A', status='in_progress')
        )
        program = adapter.last_tptp_program()
        assert program is not None
        assert program.startswith('% Generated by lkb-atp-tptp')
        assert program.endswith('\n')
        # Conjecture line should match the proposal.
        assert any(
            'conjecture' in line and 'do_proposal' in line
            for line in program.splitlines()
        )

    def test_last_tptp_program_none_before_first_call(self) -> None:
        adapter = AtpTptpSolverAdapter()
        assert adapter.last_tptp_program() is None

    def test_last_tptp_program_updates_per_solve(self) -> None:
        adapter = AtpTptpSolverAdapter()
        ctx_a = _ctx_with({'A': _task('A')})
        ctx_b = _ctx_with({'A': _task('A'), 'B': _task('B', blocked_by=['A'])})

        adapter.solve(_req(_snapshot(ctx_a), target='A', status='in_progress'))
        first_program = adapter.last_tptp_program()

        adapter.solve(_req(_snapshot(ctx_b), target='B', status='in_progress'))
        second_program = adapter.last_tptp_program()

        assert first_program is not None
        assert second_program is not None
        assert first_program != second_program