"""Solver adapter layer for Logical Kanban (F-138).

Each adapter translates between the canonical LKB :class:`SolverRequest` /
:class:`SolverResponse` contracts and a concrete symbolic engine.  Adapters are
optional: when their backing engine is not installed or not configured they
report themselves as unavailable and the pipeline falls back to conservative
``unknown`` results.

F-139 security note: external-engine adapters must never pass raw natural-language
text to a solver process.  Use :func:`encode_solver_literal` to escape task fields
before encoding them into solver input.
"""

from __future__ import annotations

import json
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .solver_limits import SolverLimitError, SolverResourceLimits, run_external_solver

if TYPE_CHECKING:
    from .types import FactsSnapshot


SolverResult = Literal['pass', 'fail', 'unknown', 'timeout', 'error']


# Characters that are unsafe in most solver surface syntaxes (SMT-LIB, Datalog,
# ASP).  We replace them with an underscore and append a stable hex suffix so
# the mapping remains deterministic and reversible for debugging.
_UNSAFE_SOLVER_CHARS = re.compile(r'[^a-zA-Z0-9_\-:.]')


# Z3 SMT-adapter: predicates we materialise from the snapshot.
# Other fact strings (Owner, Title, custom user predicates) are intentionally
# skipped because the F-131 glossary restricts Layer-4 reasoning to the 17
# canonical predicates recorded in ``clawcodex_ext/logical_kanban/glossary.py``.
_Z3_OBSERVED_PREDICATES = frozenset(
    {'Task', 'Blocks', 'Requires', 'HasAcceptanceProof'}
)
_Z3_DERIVED_BLOCKED_PREDICATE = 'Blocked'
_Z3_DERIVED_READY_PREDICATE = 'Ready'
_Z3_DERIVED_NOT_READY_PREDICATE = 'NotReady'


_FACT_PATTERN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*$', re.DOTALL)


def encode_solver_literal(text: str, *, max_length: int = 256) -> str:
    """Escape arbitrary text so it can be safely embedded in solver input.

    The result is a compact ASCII identifier with a deterministic suffix.
    Original text is never passed verbatim, preventing solver-injection or
    syntax-breaking payloads.
    """
    if not isinstance(text, str):
        text = str(text)
    truncated = text[:max_length]
    safe = _UNSAFE_SOLVER_CHARS.sub('_', truncated)
    suffix = format(hash(truncated) & 0xFFFF, '04x')
    return f'{safe}_h{suffix}'


def _parse_fact(fact: str) -> tuple[str, tuple[str, ...]] | None:
    """Parse ``Name(arg1, arg2, ...)`` into ``(Name, (arg1, arg2))`` or ``None``.

    Quoted arguments are accepted (the snapshot fact emitter encodes JSON
    strings using double quotes for ``Title`` and a handful of metadata-derived
    predicates). Nested parentheses inside quoted arguments are intentionally
    not supported — the F-131 glossary does not require them.
    """
    if not isinstance(fact, str):
        return None
    text = fact.strip()
    match = _FACT_PATTERN.match(text)
    if not match:
        return None
    name = match.group(1)
    args_raw = match.group(2).strip()
    if not args_raw:
        return name, ()
    args: list[str] = []
    if args_raw.startswith('"') and args_raw.endswith('"') and len(args_raw) >= 2:
        args.append(args_raw[1:-1])
        return name, tuple(args)
    for arg in args_raw.split(','):
        token = arg.strip()
        if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
            token = token[1:-1]
        if token:
            args.append(token)
    return name, tuple(args)


def encode_solver_facts(request: SolverRequest) -> str:
    """Encode the canonical facts of ``request`` as sanitized text for solvers.

    Task identifiers and status values are preserved; task subject/description
    fields are passed through :func:`encode_solver_literal`.  The output is a
    JSON-lines style blob that future adapters can translate into their target
    syntax without ever receiving raw user text.
    """
    snapshot = request.snapshot
    rows: list[dict[str, Any]] = []
    for task_id, task in snapshot.normalized_tasks.items():
        rows.append(
            {
                'task_id': task_id,
                'status': task['status'],
                'subject_ref': encode_solver_literal(task.get('subject', '')),
                'description_ref': encode_solver_literal(task.get('description', '')),
            }
        )
    return json.dumps(
        {
            'target_task_id': request.target_task_id,
            'target_status': request.target_status,
            'strict_acceptance': request.strict_acceptance,
            'tasks': rows,
            'facts': list(snapshot.facts),
        },
        sort_keys=True,
        default=str,
    )


@dataclass(frozen=True)
class SolverRequest:
    """Canonical input passed to every solver adapter."""

    snapshot: 'FactsSnapshot'
    target_task_id: str | None = None
    target_status: str | None = None
    strict_acceptance: bool = False
    acceptance_proof_present: bool | None = None


@dataclass(frozen=True)
class SolverResponse:
    """Canonical output produced by every solver adapter."""

    result: SolverResult
    derived_facts: tuple[str, ...] = ()
    proof_trace: tuple[dict[str, Any], ...] = ()
    violated_rule: str | None = None
    message: str = ''
    cycle_tasks: tuple[str, ...] = ()
    counterexample: dict[str, Any] | None = None
    error_info: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            'result': self.result,
            'derivedFacts': list(self.derived_facts),
            'proofTrace': list(self.proof_trace),
            'message': self.message,
        }
        if self.violated_rule is not None:
            out['violatedRule'] = self.violated_rule
        if self.cycle_tasks:
            out['cycleTasks'] = list(self.cycle_tasks)
        if self.counterexample is not None:
            out['counterexample'] = self.counterexample
        if self.error_info is not None:
            out['errorInfo'] = self.error_info
        return out


class SolverAdapter(ABC):
    """Abstract adapter from a concrete symbolic engine to LKB contracts."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short engine identifier, e.g. ``layer1-python``."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Engine version string."""

    @abstractmethod
    def available(self) -> bool:
        """Return ``True`` when the backing engine can be invoked right now."""

    @abstractmethod
    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        """Run the engine against ``request`` and return a canonical response.

        Adapters must never raise for engine-level failures; failures are
        reported as ``SolverResponse(result='error', ...)``.
        """


class Layer1SolverAdapter(SolverAdapter):
    """Adapter wrapping the in-process F-132 Python rule engine."""

    def __init__(self) -> None:
        from .rule_engine import Layer1RuleEngine

        self._engine = Layer1RuleEngine()

    @property
    def name(self) -> str:
        return 'layer1-python'

    @property
    def version(self) -> str:
        return self._engine.solver_version

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        try:
            result = self._engine.evaluate(
                request.snapshot,
                target_task_id=request.target_task_id,
                target_status=request.target_status,
                strict_acceptance=request.strict_acceptance,
                acceptance_proof_present=request.acceptance_proof_present,
            )
        except Exception as exc:  # pragma: no cover - defensive only
            return SolverResponse(
                result='error',
                message=f'Layer-1 rule engine raised {type(exc).__name__}: {exc}',
                error_info={'exception': type(exc).__name__, 'detail': str(exc)},
            )
        return SolverResponse(
            result=result.result,  # type: ignore[arg-type]
            derived_facts=result.derived_facts,
            proof_trace=result.proof_trace,
            violated_rule=result.violated_rule,
            message=result.message,
            cycle_tasks=result.cycle_tasks,
        )


class DatalogSolverAdapter(SolverAdapter):
    """Optional Layer-2 Datalog adapter (Soufflé).

    Translates the F-132 snapshot and the proposed transition into a Soufflé
    ``.dl`` program, runs it under F-139 resource limits, and inspects the
    derived ``violation`` relation to decide the outcome:

    * violation rows present           → ``fail``
    * program satisfiable, no violation → ``pass``
    * timeout / output-limit / exit    → ``timeout`` / ``unknown`` / ``error``

    The encoding mirrors the Layer-1 MVP rule set (R-002 / R-005 / R-006) as
    Datalog rules so this backend acts as a cross-checker against the Python
    engine. Snapshot-derived predicates (``blocked``, ``in_cycle``,
    ``has_acceptance_proof``) flow in as ``.input`` relations; proposal
    predicates (``do_proposal``, ``complete_proposal``, ``reopen_proposal``)
    are emitted by the encoder and asserted once via ``.input``.

    F-139: every task identifier and metadata string is routed through
    :func:`encode_solver_literal` before being concatenated into the
    Datalog atom. Raw natural-language subjects/descriptions never reach the
    solver.
    """

    engine_name = 'datalog-souffle'

    @property
    def name(self) -> str:
        return self.engine_name

    @property
    def version(self) -> str:
        if not self.available():
            return 'unavailable'
        try:
            _returncode, stdout, _stderr = run_external_solver(
                ['souffle', '--version'],
                limits=SolverResourceLimits(timeout_seconds=5, max_memory_mb=64, max_output_bytes=4096),
            )
            return (stdout or 'unknown').strip().splitlines()[0]
        except SolverLimitError as exc:
            return f'unavailable ({exc.reason})'
        except Exception as exc:  # pragma: no cover
            return f'unavailable ({type(exc).__name__})'

    def available(self) -> bool:
        if shutil.which('souffle') is None:
            return False
        try:
            run_external_solver(
                ['souffle', '--version'],
                limits=SolverResourceLimits(timeout_seconds=5, max_memory_mb=64, max_output_bytes=4096),
            )
            return True
        except Exception:
            return False

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        # Honour the ``available()`` contract first so tests/mocks can force
        # the ``engine_unavailable`` branch even when ``souffle`` is on PATH.
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='Soufflé Datalog engine is not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        try:
            return self._solve_impl(request, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - adapter must never raise
            return SolverResponse(
                result='error',
                message=f'Datalog adapter raised {type(exc).__name__}: {exc}',
                error_info={
                    'reason': 'exception',
                    'exception': type(exc).__name__,
                    'detail': str(exc),
                },
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _solve_impl(
        self,
        request: SolverRequest,
        timeout_seconds: float,
    ) -> SolverResponse:
        snapshot = request.snapshot
        program_text = self._build_program(request, snapshot)
        limits = SolverResourceLimits(
            timeout_seconds=timeout_seconds,
            max_memory_mb=512,
            max_output_bytes=8 * 1024 * 1024,
        )

        # ``violation(T)`` is the only relation we care about; we instruct
        # Soufflé to write the result CSV to a temp directory and read it
        # back. Using a temp dir (vs stdout) keeps the encoding
        # self-contained and avoids ``-D-`` parsing complications when the
        # relation is empty.
        import os
        import tempfile

        with tempfile.TemporaryDirectory(prefix='lkb-datalog-') as tmpdir:
            program_path = os.path.join(tmpdir, 'lkb_program.dl')
            facts_dir = os.path.join(tmpdir, 'facts')
            os.makedirs(facts_dir, exist_ok=True)

            # Soufflé reads ``.input`` relations from a facts directory whose
            # path mirrors the program location (``./facts``). We materialise
            # the facts alongside the program so Soufflé finds them.
            self._write_facts(request, snapshot, facts_dir)

            with open(program_path, 'w', encoding='utf-8') as handle:
                handle.write(program_text)

            try:
                returncode, stdout, stderr = run_external_solver(
                    ['souffle', '-D', facts_dir, program_path],
                    limits=limits,
                )
            except SolverLimitError as exc:
                if exc.reason == 'timeout':
                    return SolverResponse(
                        result='timeout',
                        message=f'Soufflé exceeded the {timeout_seconds}s timeout.',
                        error_info={
                            'reason': 'timeout',
                            'timeout_seconds': timeout_seconds,
                        },
                    )
                return SolverResponse(
                    result='unknown',
                    message=f'Soufflé resource limit hit: {exc.reason}.',
                    error_info={'reason': exc.reason},
                )

            violation_rows = self._read_violation_rows(facts_dir)
            verdict = self._classify_violations(request, violation_rows)

        if verdict[0] == 'fail':
            _, violated_rule, message, premises = verdict
            return SolverResponse(
                result='fail',
                derived_facts=(),
                violated_rule=violated_rule,
                message=message,
                proof_trace=(
                    {
                        'rule': violated_rule,
                        'premises': list(premises),
                        'conclusion': (
                            f'Soufflé derived a violation for '
                            f'target={request.target_task_id} '
                            f'status={request.target_status}.'
                        ),
                        'solverVersion': f'lkb-souffle/{self.version}',
                    },
                ),
            )

        if verdict[0] == 'pass':
            return SolverResponse(
                result='pass',
                derived_facts=tuple(sorted(set(snapshot.facts))),
                proof_trace=(
                    {
                        'rule': 'DL-SAT',
                        'premises': ['Snapshot facts + Layer-1 constraints + Proposal'],
                        'conclusion': (
                            f'Soufflé found no violation for '
                            f'target={request.target_task_id} '
                            f'status={request.target_status}.'
                        ),
                        'solverVersion': f'lkb-souffle/{self.version}',
                    },
                ),
                message='Soufflé satisfied the proposal under all encoded invariants.',
            )

        # ``error`` verdict (compilation failure or stray return code).
        _, _, message, error_info = verdict
        return SolverResponse(
            result='error',
            message=message,
            error_info=error_info,
        )

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _atom(value: str) -> str:
        """Wrap ``value`` as a Soufflé identifier (F-139 sanitised)."""
        return f'"{encode_solver_literal(value)}"'

    def _build_program(
        self,
        request: SolverRequest,
        snapshot: 'FactsSnapshot',
    ) -> str:
        """Build the Soufflé ``.dl`` program.

        Layout:

        1. ``.decl`` declarations for every relation that participates in
           the encoding. ``violation/1`` is the only ``.output`` relation;
           it is the verdict the runner reads back.
        2. ``.input`` declarations so Soufflé picks up the per-snapshot
           fact files we materialise in :meth:`_write_facts`.
        3. Integrity-constraint style rules translating the Layer-1 MVP
           rule set (R-002 / R-005 / R-006) into ``violation/1`` derivations.
        """
        lines: list[str] = ['// Generated by lkb-datalog']
        lines.extend(
            (
                '.decl task(t: symbol)',
                '.input task',
                '.decl blocks(a: symbol, b: symbol)',
                '.input blocks',
                '.decl requires(a: symbol, b: symbol)',
                '.input requires',
                '.decl done(t: symbol)',
                '.input done',
                '.decl doing(t: symbol)',
                '.input doing',
                '.decl pending(t: symbol)',
                '.input pending',
                '.decl blocked(t: symbol)',
                '.input blocked',
                '.decl in_cycle(t: symbol)',
                '.input in_cycle',
                '.decl has_acceptance_proof(t: symbol)',
                '.input has_acceptance_proof',
                '.decl do_proposal(t: symbol)',
                '.input do_proposal',
                '.decl complete_proposal(t: symbol)',
                '.input complete_proposal',
                '.decl reopen_proposal(t: symbol)',
                '.input reopen_proposal',
                '.decl strict_acceptance()',
                '.input strict_acceptance',
                '.decl violation(t: symbol)',
                '.output violation',
            )
        )

        # R-002: blocked cannot enter in_progress.
        lines.append(
            'violation(T) :- do_proposal(T), blocked(T).'
        )
        # R-006: cycle cannot enter in_progress.
        lines.append(
            'violation(T) :- do_proposal(T), in_cycle(T).'
        )
        # R-005: strict acceptance + completion requires proof.
        lines.append(
            'violation(T) :- complete_proposal(T), strict_acceptance(), '
            '!has_acceptance_proof(T).'
        )
        # Proposal sanity: target must be a known task.
        lines.append(
            'violation(T) :- do_proposal(T), !task(T).'
        )
        lines.append(
            'violation(T) :- complete_proposal(T), !task(T).'
        )
        lines.append(
            'violation(T) :- reopen_proposal(T), !task(T).'
        )
        return '\n'.join(lines) + '\n'

    def _write_facts(
        self,
        request: SolverRequest,
        snapshot: 'FactsSnapshot',
        facts_dir: str,
    ) -> None:
        """Materialise Soufflé ``.facts`` files for every ``.input`` relation."""
        import os

        # Tasks
        with open(
            os.path.join(facts_dir, 'task.facts'), 'w', encoding='utf-8'
        ) as handle:
            for task_id in sorted(snapshot.normalized_tasks):
                handle.write(f'{self._atom(task_id)}\n')

        # Blocks / Requires
        seen_blocks: set[tuple[str, str]] = set()
        seen_requires: set[tuple[str, str]] = set()
        blocks_path = os.path.join(facts_dir, 'blocks.facts')
        requires_path = os.path.join(facts_dir, 'requires.facts')
        with open(blocks_path, 'w', encoding='utf-8') as blocks_handle:
            with open(requires_path, 'w', encoding='utf-8') as requires_handle:
                for fact in snapshot.facts:
                    parsed = _parse_fact(fact)
                    if parsed is None:
                        continue
                    name, args = parsed
                    if name == 'Blocks' and len(args) == 2:
                        key = (args[0], args[1])
                        if key in seen_blocks:
                            continue
                        seen_blocks.add(key)
                        blocks_handle.write(
                            f'{self._atom(args[0])}\t{self._atom(args[1])}\n'
                        )
                    elif name == 'Requires' and len(args) == 2:
                        key = (args[0], args[1])
                        if key in seen_requires:
                            continue
                        seen_requires.add(key)
                        requires_handle.write(
                            f'{self._atom(args[0])}\t{self._atom(args[1])}\n'
                        )

        # Status predicates
        self._write_unary_facts(
            os.path.join(facts_dir, 'done.facts'),
            snapshot.completed_ids,
        )
        in_progress_ids = sorted(
            task_id
            for task_id, task in snapshot.normalized_tasks.items()
            if task.get('status') == 'in_progress'
        )
        self._write_unary_facts(
            os.path.join(facts_dir, 'doing.facts'), in_progress_ids
        )
        pending_ids = sorted(
            task_id
            for task_id, task in snapshot.normalized_tasks.items()
            if task.get('status') == 'pending'
        )
        self._write_unary_facts(
            os.path.join(facts_dir, 'pending.facts'), pending_ids
        )

        # Snapshot-derived predicates
        self._write_unary_facts(
            os.path.join(facts_dir, 'blocked.facts'),
            sorted(snapshot.blocked_ids),
        )
        self._write_unary_facts(
            os.path.join(facts_dir, 'in_cycle.facts'),
            sorted(snapshot.cycle_task_ids),
        )

        # Acceptance proofs
        acceptance_ids = sorted(
            task_id
            for task_id, task in snapshot.normalized_tasks.items()
            if (task.get('metadata') or {}).get('lkb', {}).get('acceptance_proof')
        )
        self._write_unary_facts(
            os.path.join(facts_dir, 'has_acceptance_proof.facts'),
            acceptance_ids,
        )

        # Proposal
        target = request.target_task_id
        target_status = request.target_status
        with open(
            os.path.join(facts_dir, 'do_proposal.facts'), 'w', encoding='utf-8'
        ) as handle:
            if target_status == 'in_progress' and target is not None:
                handle.write(f'{self._atom(target)}\n')
        with open(
            os.path.join(facts_dir, 'complete_proposal.facts'),
            'w',
            encoding='utf-8',
        ) as handle:
            if target_status == 'completed' and target is not None:
                handle.write(f'{self._atom(target)}\n')
        with open(
            os.path.join(facts_dir, 'reopen_proposal.facts'),
            'w',
            encoding='utf-8',
        ) as handle:
            if target_status == 'pending' and target is not None:
                handle.write(f'{self._atom(target)}\n')

        # Strict acceptance flag
        with open(
            os.path.join(facts_dir, 'strict_acceptance.facts'),
            'w',
            encoding='utf-8',
        ) as handle:
            if request.strict_acceptance:
                handle.write('1\n')

    @staticmethod
    def _write_unary_facts(path: str, task_ids: list[str]) -> None:
        with open(path, 'w', encoding='utf-8') as handle:
            for task_id in task_ids:
                handle.write(f'"{encode_solver_literal(task_id)}"\n')

    @staticmethod
    def _read_violation_rows(facts_dir: str) -> tuple[str, ...]:
        """Read the ``violation.csv`` file produced by Soufflé."""
        import os

        path = os.path.join(facts_dir, 'violation.csv')
        if not os.path.exists(path):
            return ()
        rows: list[str] = []
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                # Soufflé wraps string atoms in double quotes; strip them.
                if line.startswith('"') and line.endswith('"'):
                    line = line[1:-1]
                rows.append(line)
        return tuple(rows)

    @staticmethod
    def _classify_violations(
        request: SolverRequest,
        violation_rows: tuple[str, ...],
    ) -> tuple[str, str | None, str, Any]:
        """Map violation rows back to Layer-1 rule codes.

        Always returns a 4-tuple ``(tag, rule, message, payload)`` where:

        * ``tag`` is ``'pass'``, ``'fail'``, or ``'error'``
        * ``rule`` is the rule code (or ``None`` for ``pass``/``error``)
        * ``message`` is the human-readable verdict
        * ``payload`` is ``premises`` for ``fail`` or ``error_info`` for
          ``error`` (unused for ``pass``)
        """
        target = request.target_task_id
        target_status = request.target_status
        snapshot = request.snapshot

        if not violation_rows:
            return ('pass', None, '', None)

        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.cycle_task_ids
        ):
            cycle = tuple(sorted(snapshot.cycle_task_ids))
            return (
                'fail',
                'R-006',
                f'Task {target} is part of a dependency cycle '
                f'({{{", ".join(cycle)}}}) and cannot enter in_progress.',
                tuple(f'Cycle({t})' for t in cycle),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.blocked_ids
        ):
            blockers = tuple(
                sorted(
                    b for b in snapshot.blocked_by.get(target, ())
                    if b not in snapshot.completed_ids
                )
            )
            return (
                'fail',
                'R-002',
                f'Task {target} cannot enter in_progress because its '
                f'active blockers remain: {", ".join(blockers) or "<unknown>"}.',
                tuple(f'Requires({b}, {target})' for b in blockers),
            )
        if (
            request.strict_acceptance
            and target is not None
            and target_status == 'completed'
            and not request.acceptance_proof_present
        ):
            return (
                'fail',
                'R-005',
                f'Task {target} requires an acceptance proof in strict mode.',
                (
                    f'StrictAcceptance({target})',
                    f'Not(HasAcceptanceProof({target}))',
                ),
            )
        if (
            target is not None
            and target not in snapshot.normalized_tasks
        ):
            return (
                'fail',
                'LKB-TRANSITION-001',
                f'Task {target} is not present in the current snapshot.',
                (f'Task({target})',),
            )
        return (
            'fail',
            'DL-UNSAT',
            f'Soufflé produced {len(violation_rows)} violation row(s); '
            'no Layer-1 rule matched.',
            ('Snapshot facts + Layer-1 constraints + Proposal',),
        )


class ClingoSolverAdapter(SolverAdapter):
    """Optional Layer-3 ASP/clingo adapter.

    Translates the snapshot and the proposal into an Answer Set Programming
    (ASP) program. The decision is SAT-based:

    * ``SAT``          → ``pass``   (an answer set exists)
    * ``UNSAT``        → ``fail``   (no answer set satisfies all integrity
                                      constraints)
    * ``UNKNOWN``      → ``unknown`` (clingo could not decide inside timeout)

    The encoding mirrors the Layer-1 MVP rule set in ASP integrity constraints
    so that this adapter can act as a cross-checker against the Python engine.
    F-139 is honoured via :class:`clingo.Function`: every task identifier and
    domain argument is funnelled through ``clingo``'s own ``Symbol`` API, so
    raw natural-language text never reaches solver input as a raw string.
    """

    engine_name = 'asp-clingo'

    def __init__(self) -> None:
        self._cached_clingo: Any | None = None

    @property
    def name(self) -> str:
        return self.engine_name

    @property
    def version(self) -> str:
        clingo = self._import_clingo()
        if clingo is None:
            return 'unavailable'
        try:
            return getattr(clingo, '__version__', 'unknown')
        except Exception:  # pragma: no cover - defensive only
            return 'unknown'

    def available(self) -> bool:
        return self._import_clingo() is not None

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        # Honour the ``available()`` contract first so mocks/tests can force
        # the ``engine_unavailable`` branch.
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='clingo Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        clingo = self._import_clingo()
        if clingo is None:  # pragma: no cover - redundant guard
            return SolverResponse(
                result='unknown',
                message='clingo Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        try:
            return self._solve_impl(clingo, request, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - adapter must never raise
            return SolverResponse(
                result='error',
                message=f'Clingo adapter raised {type(exc).__name__}: {exc}',
                error_info={
                    'reason': 'exception',
                    'exception': type(exc).__name__,
                    'detail': str(exc),
                },
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _import_clingo(self) -> Any:
        if self._cached_clingo is not None:
            return self._cached_clingo
        try:
            import clingo
        except Exception:
            return None
        self._cached_clingo = clingo
        return clingo

    def _solve_impl(
        self,
        clingo: Any,
        request: SolverRequest,
        timeout_seconds: float,
    ) -> SolverResponse:
        snapshot = request.snapshot
        # Suppress informational grounder messages ("atom does not occur in
        # any rule head") that fire for atoms we deliberately use only in
        # integrity-constraint bodies (e.g. ``blocked(T)``, ``in_cycle(T)``).
        # The default logger writes them to stderr, which would clutter
        # caller output without adding any decision-relevant signal.
        atom_undefined = getattr(clingo.MessageCode, 'AtomUndefined', None)
        logger = self._make_clingo_logger(atom_undefined)
        control = clingo.Control(logger=logger)
        # ``models = 0`` — we only care about the existence of any answer
        # set, not enumerating all of them. Conflicts limit provides a soft
        # budget so clingo does not run away on large snapshots; the
        # wall-clock guard is enforced upstream by ``SolverPipeline``.
        control.configuration.solve.models = '0'
        try:
            control.configuration.solve['--solve-limit'] = (
                str(int(timeout_seconds * 1000)),
                'time',
            )
        except (KeyError, TypeError):
            # Older clingo versions: just skip the limit. Wall-clock is still
            # enforced by ``SolverPipeline``.
            pass

        program_text, _prelude = self._build_program(request, snapshot)
        try:
            control.add('base', [], program_text)
        except Exception as exc:
            return SolverResponse(
                result='error',
                message=f'Clingo rejected the generated program: {exc}',
                error_info={'reason': 'program_parse_error', 'detail': str(exc)},
            )
        try:
            control.ground([('base', [])])
        except Exception as exc:
            return SolverResponse(
                result='error',
                message=f'Clingo failed to ground the program: {exc}',
                error_info={'reason': 'grounding_error', 'detail': str(exc)},
            )

        try:
            solve_result = control.solve(yield_=False)
        except Exception as exc:
            return SolverResponse(
                result='error',
                message=f'Clingo solve raised {type(exc).__name__}: {exc}',
                error_info={'reason': 'solver_exception', 'detail': str(exc)},
            )

        # clingo 5.x uses ``bool`` for the satisfiable bit and a separate
        # ``unknown`` flag rather than a tri-state enum. See
        # https://potassco.org/clingo/python-api/5.8/clingo.html#clingo.SolveResult
        derived_facts = tuple(sorted(set(snapshot.facts)))
        if solve_result.satisfiable:
            return SolverResponse(
                result='pass',
                derived_facts=derived_facts,
                proof_trace=(
                    {
                        'rule': 'ASP-SAT',
                        'premises': ['Snapshot facts + Layer-1 constraints + Proposal'],
                        'conclusion': (
                            f'Clingo found an answer set for '
                            f'target={request.target_task_id} '
                            f'status={request.target_status}.'
                        ),
                        'solverVersion': f'lkb-clingo/{self.version}',
                    },
                ),
                message='Clingo found an answer set satisfying the proposal.',
            )
        if solve_result.unsatisfiable:
            violated, message, premises = self._classify_unsat(request)
            return SolverResponse(
                result='fail',
                derived_facts=(),
                violated_rule=violated,
                message=message,
                proof_trace=(
                    {
                        'rule': violated,
                        'premises': list(premises),
                        'conclusion': (
                            f'No answer set satisfies the proposal '
                            f'(target={request.target_task_id}, '
                            f'status={request.target_status}).'
                        ),
                        'solverVersion': f'lkb-clingo/{self.version}',
                    },
                ),
            )
        # ``unknown`` is set when clingo exhausted its budget without
        # producing a verdict; surface as ``unknown`` so the pipeline
        # aggregation treats it as uncertain rather than as a fail.
        return SolverResponse(
            result='unknown',
            message='Clingo returned UNKNOWN within the configured budget.',
            error_info={'reason': 'asp_unknown'},
        )

    # ------------------------------------------------------------------
    # ASP encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _asp_string(value: str) -> str:
        """Escape a string for use as an ASP quoted atom.

        Clingo allows arbitrary characters inside ``"..."``; the only
        forbidden character is the backslash and the literal double quote.
        ``encode_solver_literal`` already scrubs hostile subjects; we apply
        it here too so subjects keep F-139-safe shapes even outside the Z3
        encoder.
        """
        escaped = encode_solver_literal(value)
        return f'"{escaped}"'

    @staticmethod
    def _make_clingo_logger(atom_undefined: Any) -> Any:
        """Build a clingo logger that drops ``AtomUndefined`` notices only.

        The adapter encodes snapshot-derived atoms (``blocked``,
        ``in_cycle``, ``has_acceptance_proof``, etc.) only as facts and
        only references them inside ``:-`` integrity-constraint bodies.
        Clingo's grounder therefore emits an ``AtomUndefined`` info notice
        for each such atom — those are not warnings about correctness,
        they merely observe that the atom is not derived by a rule head —
        so we drop them. Anything that clingo classifies as a real
        warning or error is preserved so genuine grounding problems still
        surface via stderr.
        """
        import sys

        def logger(code: Any, message: str) -> None:
            if atom_undefined is not None and code == atom_undefined:
                return
            print(f'clingo[{code}]: {message}', file=sys.stderr)

        return logger

    def _build_program(
        self,
        request: SolverRequest,
        snapshot: 'FactsSnapshot',
    ) -> tuple[str, dict[str, Any]]:
        """Return ``(program_text, prelude_metadata)``.

        The ASP program encodes:

        1. ``task(T)`` for every task in the snapshot.
        2. ``blocks(A, B)`` / ``requires(A, B)`` from observed facts.
        3. ``done(T)`` for terminal tasks and ``has_acceptance_proof(T)`` for
           tasks with proof metadata.
        4. Snapshot-derived ``blocked(T)`` and ``in_cycle(T)`` predicates.
        5. Optional ``strict_acceptance.`` flag in strict mode.
        6. The proposal: a single ``target(T)`` atom and a single
           ``do_proposal(T)`` / ``complete_proposal(T)`` / ``reopen_proposal(T)``
           atom.
        7. Integrity constraints matching the Layer-1 rules.
        """
        lines: list[str] = ['% Generated by lkb-clingo-asp']
        target = request.target_task_id
        target_status = request.target_status

        # 1. task atoms
        lines.append('% --- task universe ---')
        for task_id in sorted(snapshot.normalized_tasks):
            lines.append(f'task({self._asp_string(task_id)}).')

        # 2. dependency edges via the canonical fact list
        lines.append('% --- observed dependency edges ---')
        seen_edges: set[tuple[str, str]] = set()
        for fact in snapshot.facts:
            parsed = _parse_fact(fact)
            if parsed is None:
                continue
            name, args = parsed
            if name == 'Blocks' and len(args) == 2:
                key = ('blocks', args[0], args[1])
                if key in seen_edges:
                    continue
                seen_edges.add(('blocks', args[0], args[1]))
                lines.append(
                    f'blocks({self._asp_string(args[0])}, {self._asp_string(args[1])}).'
                )
            elif name == 'Requires' and len(args) == 2:
                key = ('requires', args[0], args[1])
                if key in seen_edges:
                    continue
                seen_edges.add(('requires', args[0], args[1]))
                lines.append(
                    f'requires({self._asp_string(args[0])}, {self._asp_string(args[1])}).'
                )

        # 3. terminal statuses & acceptance proofs
        lines.append('% --- terminal statuses + acceptance proofs ---')
        for task_id in sorted(snapshot.completed_ids):
            lines.append(f'done({self._asp_string(task_id)}).')
        for task_id, task in snapshot.normalized_tasks.items():
            metadata = task.get('metadata') or {}
            lkb = metadata.get('lkb') or {}
            if lkb.get('acceptance_proof'):
                lines.append(
                    f'has_acceptance_proof({self._asp_string(task_id)}).'
                )

        # 4. snapshot-derived
        lines.append('% --- snapshot-derived facts ---')
        for tid in sorted(snapshot.blocked_ids):
            lines.append(f'blocked({self._asp_string(tid)}).')
        for tid in sorted(snapshot.cycle_task_ids):
            lines.append(f'in_cycle({self._asp_string(tid)}).')

        # 5. strict acceptance flag
        if request.strict_acceptance:
            lines.append('strict_acceptance.')

        # 6. proposal
        lines.append('% --- proposal ---')
        if target is not None:
            if target not in snapshot.normalized_tasks:
                # Mirror the SMT adapter's behaviour: surface as a structured
                # denial via the integrity-constraint approach below. Emit a
                # sentinel ``target/1`` atom without ``task/1`` so the
                # integrity constraint can detect the mismatch.
                lines.append(f'target({self._asp_string(target)}).')
            else:
                lines.append(f'target({self._asp_string(target)}).')
                if target_status == 'in_progress':
                    lines.append(
                        f'do_proposal({self._asp_string(target)}).'
                    )
                elif target_status == 'completed':
                    lines.append(
                        f'complete_proposal({self._asp_string(target)}).'
                    )
                elif target_status == 'pending':
                    lines.append(
                        f'reopen_proposal({self._asp_string(target)}).'
                    )
                # other statuses are silently absent — the integrity
                # constraints will simply not fire, and clingo reports SAT.

        # 7. integrity constraints (== Layer-1 rule violations)
        lines.append('% --- integrity constraints (Layer-1 rules) ---')
        # R-002: blocked cannot enter in_progress
        lines.append(':- do_proposal(T), blocked(T).')
        # R-006: cycle cannot enter in_progress
        lines.append(':- do_proposal(T), in_cycle(T).')
        # R-005: strict acceptance + completion requires proof
        lines.append(
            ':- complete_proposal(T), strict_acceptance, not has_acceptance_proof(T).'
        )
        # target sanity
        lines.append(':- target(T), not task(T).')

        prelude = {
            'target': target,
            'target_status': target_status,
            'strict_acceptance': request.strict_acceptance,
            'tasks': len(snapshot.normalized_tasks),
            'edges': len(seen_edges),
            'messages': [],
        }
        return '\n'.join(lines) + '\n', prelude

    @staticmethod
    def _classify_unsat(
        request: SolverRequest,
    ) -> tuple[str, str, tuple[str, ...]]:
        target = request.target_task_id
        target_status = request.target_status
        snapshot = request.snapshot
        if (
            target is not None
            and target not in snapshot.normalized_tasks
        ):
            return (
                'LKB-TRANSITION-001',
                f'Task {target} is not present in the current snapshot.',
                (f'Task({target})',),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.cycle_task_ids
        ):
            cycle = tuple(sorted(snapshot.cycle_task_ids))
            return (
                'R-006',
                f'Task {target} is part of a dependency cycle '
                f'({{{", ".join(cycle)}}}) and cannot enter in_progress.',
                tuple(f'Cycle({t})' for t in cycle),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.blocked_ids
        ):
            blockers = tuple(
                sorted(
                    b for b in snapshot.blocked_by.get(target, ())
                    if b not in snapshot.completed_ids
                )
            )
            return (
                'R-002',
                f'Task {target} cannot enter in_progress because its '
                f'active blockers remain: {", ".join(blockers) or "<unknown>"}.',
                tuple(f'Requires({b}, {target})' for b in blockers),
            )
        if (
            request.strict_acceptance
            and target is not None
            and target_status == 'completed'
            and not request.acceptance_proof_present
        ):
            return (
                'R-005',
                f'Task {target} requires an acceptance proof in strict mode.',
                (
                    f'StrictAcceptance({target})',
                    f'Not(HasAcceptanceProof({target}))',
                ),
            )
        return (
            'ASP-UNSAT',
            'Clingo proved the proposal unsatisfiable; no Layer-1 rule matched.',
            ('Snapshot facts + Layer-1 constraints + Proposal',),
        )


class Z3SolverAdapter(SolverAdapter):
    """Optional Layer-4 SMT/Z3 adapter.

    Encodes the snapshot and the proposed transition into SMT formulas and
    asks Z3 for satisfiability. The decision is conservative:

    * ``sat``      → ``pass``  (a consistent world exists with the proposal)
    * ``unsat``    → ``fail``  (no consistent world satisfies the proposal)
    * ``unknown``  → ``unknown`` (Z3 timed out or returned an indeterminate verdict)

    The adapter participates in the F-138 conservative aggregation policy. By
    itself, Z3 is at most as accurate as Layer-1; it adds value as a
    cross-checker that can detect contradictions the Layer-1 Python loop
    misses, especially around cyclic dependencies and strict-acceptance
    invariants. The encoding deliberately maps the MVP Layer-1 rule set
    (R-002/R-005/R-006) onto Z3 implication rules so the two backends stay in
    lock-step.

    F-139: raw subject/description text never reaches the SMT solver; every
    string argument is scrubbed via :func:`encode_solver_literal` before being
    concatenated into the SMT-LIB identifier name.
    """

    #: Identifier used in audit/error payloads. Pulled out as a class constant
    #: so tests can match on it without coupling to the class hierarchy.
    engine_name = 'smt-z3'

    def __init__(self) -> None:
        self._cached_z3: Any | None = None

    @property
    def name(self) -> str:
        return self.engine_name

    @property
    def version(self) -> str:
        z3 = self._import_z3()
        if z3 is None:
            return 'unavailable'
        try:
            return z3.get_version_string()
        except Exception:  # pragma: no cover - defensive only
            return 'unknown'

    def available(self) -> bool:
        return self._import_z3() is not None

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        # Honour the ``available()`` contract first so callers (and tests)
        # that override availability — for example to force the
        # ``engine_unavailable`` branch — get the expected short-circuit
        # even when the ``z3-solver`` package is installed in the env.
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='Z3 Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        z3 = self._import_z3()
        if z3 is None:  # pragma: no cover - redundant guard after ``available``
            return SolverResponse(
                result='unknown',
                message='Z3 Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        try:
            return self._solve_impl(z3, request, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - adapter must never raise
            return SolverResponse(
                result='error',
                message=f'Z3 adapter raised {type(exc).__name__}: {exc}',
                error_info={
                    'reason': 'exception',
                    'exception': type(exc).__name__,
                    'detail': str(exc),
                },
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _import_z3(self) -> Any:
        """Return the ``z3`` module or ``None`` if it is not importable.

        Cached after the first successful import to avoid repeated import
        cost during batched pipeline runs.
        """
        if self._cached_z3 is not None:
            return self._cached_z3
        try:
            import z3
        except Exception:
            return None
        self._cached_z3 = z3
        return z3

    def _solve_impl(
        self,
        z3: Any,
        request: SolverRequest,
        timeout_seconds: float,
    ) -> SolverResponse:
        """Translate ``request`` into SMT assertions and run Z3."""
        timeout_ms = max(1, int(timeout_seconds * 1000))
        solver = z3.Solver()
        solver.set('timeout', timeout_ms)
        solver.set('smt.ematching', True)

        snapshot = request.snapshot
        predicate_cache: dict[tuple[str, tuple[str, ...]], Any] = {}

        def predicate(name: str, *args: str) -> Any:
            key = (name, tuple(args))
            if key not in predicate_cache:
                identifier = self._build_identifier(name, args)
                predicate_cache[key] = z3.Bool(identifier)
            return predicate_cache[key]

        # ------------------------------------------------------------------
        # Step 1 — assert observed snapshot facts (F-139 sanitised)
        # ------------------------------------------------------------------
        for fact in snapshot.facts:
            parsed = _parse_fact(fact)
            if parsed is None:
                continue
            name, args = parsed
            if name not in _Z3_OBSERVED_PREDICATES:
                continue
            solver.add(predicate(name, *args) == True)

        for task_id, task in snapshot.normalized_tasks.items():
            metadata = task.get('metadata') or {}
            lkb_metadata = metadata.get('lkb') or {}
            if lkb_metadata.get('acceptance_proof'):
                solver.add(predicate('HasAcceptanceProof', task_id) == True)
            if task.get('status') == 'completed':
                # Terminal state — encode as observed ``Done`` fact.
                solver.add(predicate('Done', task_id) == True)

        # ------------------------------------------------------------------
        # Step 2 — assert derivations produced by the Layer-1 rule engine
        # ------------------------------------------------------------------
        for blocked_id in sorted(snapshot.blocked_ids):
            solver.add(predicate(_Z3_DERIVED_BLOCKED_PREDICATE, blocked_id) == True)
        for ready_id in sorted(snapshot.ready_ids):
            solver.add(predicate(_Z3_DERIVED_READY_PREDICATE, ready_id) == True)
        for cycle_id in sorted(snapshot.cycle_task_ids):
            solver.add(
                predicate(_Z3_DERIVED_NOT_READY_PREDICATE, cycle_id) == True
            )

        # ------------------------------------------------------------------
        # Step 3 — encode Layer-1 MVP invariant rules as Z3 implications.
        # R-001 is implicitly encoded by ``snapshot.blocked_ids`` above;
        # R-003/R-004 only shape the proof trace and have no decision impact.
        # ------------------------------------------------------------------
        for task_id in sorted(snapshot.normalized_tasks):
            blocked = predicate(_Z3_DERIVED_BLOCKED_PREDICATE, task_id)
            doing = predicate('Doing', task_id)
            solver.add(z3.Implies(blocked == True, doing == False))

            if task_id in snapshot.cycle_task_ids:
                notready = predicate(
                    _Z3_DERIVED_NOT_READY_PREDICATE, task_id
                )
                solver.add(z3.Implies(notready == True, doing == False))

        if request.strict_acceptance:
            for task_id in sorted(snapshot.normalized_tasks):
                done = predicate('Done', task_id)
                proof = predicate('HasAcceptanceProof', task_id)
                solver.add(z3.Implies(done == True, proof == True))

        # ------------------------------------------------------------------
        # Step 4 — assert the proposal under test.
        # ------------------------------------------------------------------
        target = request.target_task_id
        target_status = request.target_status
        if (target is None) != (target_status is None):
            return SolverResponse(
                result='unknown',
                message='target_task_id and target_status must be provided together.',
                error_info={'reason': 'incomplete_query'},
            )
        if target is not None and target_status is not None:
            if target not in snapshot.normalized_tasks:
                return SolverResponse(
                    result='fail',
                    violated_rule='LKB-TRANSITION-001',
                    message=f'Task {target} is not present in the current snapshot.',
                    proof_trace=(
                        self._proof_entry(
                            'LKB-TRANSITION-001',
                            (f'Task({target})',),
                            f'Not(Exists Task({target}))',
                        ),
                    ),
                )
            if target_status == 'in_progress':
                solver.add(predicate('Doing', target) == True)
            elif target_status == 'completed':
                solver.add(predicate('Done', target) == True)
                # Re-opening ``completed → pending`` should still be allowed,
                # so we leave ``Pending(target)`` unconstrained. The mutex
                # check below also removes the contradiction if Pending(True)
                # collides with Done(True).
                solver.add(z3.Implies(
                    predicate('Done', target) == True,
                    predicate('Pending', target) == False,
                ))
                if (
                    request.strict_acceptance
                    and not request.acceptance_proof_present
                ):
                    # Pin the proof predicate to ``False`` so the strict-mode
                    # invariant ``Done ⇒ HasAcceptanceProof`` becomes
                    # unsatisfiable together with ``Done(target) = True``.
                    solver.add(
                        predicate('HasAcceptanceProof', target) == False
                    )
            elif target_status == 'pending':
                solver.add(predicate('Pending', target) == True)
            elif target_status == 'deleted':
                # Delete is a structural change and does not interact with
                # the state-machine invariants encoded here. Surface as
                # ``unknown`` so the pipeline falls back to Layer-1's
                # structural validator.
                return SolverResponse(
                    result='unknown',
                    message='Z3 adapter does not encode delete transitions.',
                    error_info={'reason': 'unsupported_status'},
                )
            else:
                return SolverResponse(
                    result='unknown',
                    message=f'Unsupported target status: {target_status!r}.',
                    error_info={'reason': 'unsupported_status'},
                )

        verdict = solver.check()
        derived_facts = tuple(sorted(set(snapshot.facts)))
        if verdict == z3.sat:
            return SolverResponse(
                result='pass',
                derived_facts=derived_facts,
                proof_trace=(
                    self._proof_entry(
                        'Z3-SAT',
                        ('Snapshot facts + Layer-1 invariants + Proposal',),
                        f'Z3 satisfied the proposal (target={target}, status={target_status}).',
                    ),
                ),
                message='Z3 satisfied the proposal under all encoded invariants.',
            )
        if verdict == z3.unsat:
            violated, message, premises = self._classify_unsat(request)
            return SolverResponse(
                result='fail',
                derived_facts=(),
                violated_rule=violated,
                message=message,
                proof_trace=(
                    self._proof_entry(
                        violated,
                        premises,
                        f'No consistent world satisfies the proposal (target={target}, status={target_status}).',
                    ),
                ),
            )
        return SolverResponse(
            result='unknown',
            message='Z3 returned UNKNOWN within the timeout.',
            error_info={'reason': 'z3_unknown'},
        )

    @staticmethod
    def _build_identifier(name: str, args: tuple[str, ...]) -> str:
        """Build an SMT-LIB-safe boolean identifier for ``name(args)``.

        Every argument is routed through :func:`encode_solver_literal` to
        honour F-139 — raw subject/description text never appears in solver
        identifiers.
        """
        if not args:
            return f'LKB_{name}'
        parts = [name] + [encode_solver_literal(arg) for arg in args]
        return '_'.join(parts)

    @staticmethod
    def _proof_entry(
        rule: str,
        premises: tuple[str, ...],
        conclusion: str,
    ) -> dict[str, Any]:
        return {
            'rule': rule,
            'premises': list(premises),
            'conclusion': conclusion,
            'solverVersion': 'lkb-z3',
        }

    @staticmethod
    def _classify_unsat(
        request: SolverRequest,
    ) -> tuple[str, str, tuple[str, ...]]:
        """Map a Z3 UNSAT verdict back to a recognisable Layer-1 rule."""
        target = request.target_task_id
        target_status = request.target_status
        snapshot = request.snapshot
        # Cycle membership takes precedence: cyclic tasks are typically also
        # marked ``blocked``, but the cycle itself is the deeper structural
        # reason, and the user-facing rule should reflect that.
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.cycle_task_ids
        ):
            cycle = tuple(sorted(snapshot.cycle_task_ids))
            return (
                'R-006',
                f'Task {target} is part of a dependency cycle '
                f'({{{", ".join(cycle)}}}) and cannot enter in_progress.',
                tuple(f'Cycle({t})' for t in cycle),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.blocked_ids
        ):
            blockers = tuple(
                sorted(
                    b for b in snapshot.blocked_by.get(target, ())
                    if b not in snapshot.completed_ids
                )
            )
            premises = tuple(f'Requires({b}, {target})' for b in blockers)
            return (
                'R-002',
                f'Task {target} cannot enter in_progress because its '
                f'active blockers remain: {", ".join(blockers) or "<unknown>"}.',
                premises,
            )
        if (
            request.strict_acceptance
            and target is not None
            and target_status == 'completed'
            and not request.acceptance_proof_present
        ):
            return (
                'R-005',
                f'Task {target} requires an acceptance proof in strict mode.',
                (
                    f'StrictAcceptance({target})',
                    f'Not(HasAcceptanceProof({target}))',
                ),
            )
        return (
            'Z3-UNSAT',
            'Z3 proved the proposal unsatisfiable; no Layer-1 rule matched.',
            ('Snapshot facts + Layer-1 invariants + Proposal',),
        )


class AtpTptpSolverAdapter(SolverAdapter):
    """Optional Layer-5 ATP/TPTP adapter.

    The adapter translates the F-132 snapshot and the proposal into a
    TPTP FOF program and runs an in-process first-order refutation
    prover (:mod:`solver_atp`) against it. The decision is conservative:

    * empty clause derivable (refutation) → ``fail``
    * saturation reached, no contradiction → ``pass``
    * saturation cap hit, no decision       → ``unknown``

    The in-process prover is hand-rolled and intentionally narrow: it
    handles the LKB Horn-ish FOL fragment (predicate symbols, ground
    constants, universal quantification, no equality). The TPTP program
    emitted for audit is well-formed and could be piped to ``vampire``
    or ``eprover`` if either were on ``PATH``; the prover module is
    isolated from the TPTP syntax so a future swap to a subprocess
    backend does not require touching this class.

    F-139: every task identifier is sanitised via
    :func:`encode_solver_literal` before being concatenated into TPTP
    atoms. Raw subject/description text never reaches the audit payload.

    The adapter is always available because the prover lives in-process;
    no external binary is required.
    """

    engine_name = 'atp-tptp'
    _PROVER_VERSION = 'lkb-atp/0.1.0'

    def __init__(self) -> None:
        self._last_tptp_program: str | None = None

    @property
    def name(self) -> str:
        return self.engine_name

    @property
    def version(self) -> str:
        return self._PROVER_VERSION

    def available(self) -> bool:
        return True

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        try:
            return self._solve_impl(request, timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - adapter must never raise
            return SolverResponse(
                result='error',
                message=f'ATP/TPTP adapter raised {type(exc).__name__}: {exc}',
                error_info={
                    'reason': 'exception',
                    'exception': type(exc).__name__,
                    'detail': str(exc),
                },
            )

    def last_tptp_program(self) -> str | None:
        """Return the TPTP FOF program emitted by the most recent solve.

        Useful for debugging and audit: callers can inspect the exact
        axioms and conjecture that fed the prover. Returns ``None``
        before the first :meth:`solve` call.
        """
        return self._last_tptp_program

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _solve_impl(
        self,
        request: SolverRequest,
        timeout_seconds: float,
    ) -> SolverResponse:
        from .solver_atp import (
            emit_tptp_program,
            prove_lkb_request,
            task_constants,
        )

        snapshot = request.snapshot
        # Pull metadata about acceptance proofs out of the snapshot so the
        # prover can assert ``has_acceptance_proof(c)`` for tasks that
        # carry an explicit ``acceptance_proof`` marker.
        has_proof_ids = frozenset(
            task_id
            for task_id, task in snapshot.normalized_tasks.items()
            if (task.get('metadata') or {}).get('lkb', {}).get('acceptance_proof')
        )
        completed_ids = frozenset(snapshot.completed_ids)
        snapshot_task_ids = frozenset(snapshot.normalized_tasks)
        constants = task_constants(snapshot.normalized_tasks)

        verdict, meta = prove_lkb_request(
            constants=constants,
            blocked_ids=frozenset(snapshot.blocked_ids),
            cycle_ids=frozenset(snapshot.cycle_task_ids),
            has_proof_ids=has_proof_ids,
            completed_ids=completed_ids,
            strict_acceptance=request.strict_acceptance,
            proposal_target=request.target_task_id,
            proposal_status=request.target_status,
            snapshot_task_ids=snapshot_task_ids,
        )

        # Cache the TPTP program emitted for this request so callers can
        # inspect / replay it via vampire or eprover.
        emit_constants: tuple[str, ...] = tuple(
            sorted(
                set(constants)
                | ({request.target_task_id} if request.target_task_id else set())
            )
        )
        self._last_tptp_program = emit_tptp_program(
            constants=emit_constants,
            blocked_ids=frozenset(snapshot.blocked_ids),
            cycle_ids=frozenset(snapshot.cycle_task_ids),
            has_proof_ids=has_proof_ids,
            strict_acceptance=request.strict_acceptance,
            proposal_target=request.target_task_id,
            proposal_status=request.target_status,
        )

        if verdict == 'pass':
            return SolverResponse(
                result='pass',
                derived_facts=tuple(sorted(set(snapshot.facts))),
                proof_trace=(
                    {
                        'rule': 'ATP-SAT',
                        'premises': ['Snapshot facts + Layer-1 FOL invariants + Proposal'],
                        'conclusion': (
                            f'TPTP prover found a model satisfying the proposal '
                            f'(target={request.target_task_id}, '
                            f'status={request.target_status}).'
                        ),
                        'solverVersion': self.version,
                        'clauseCount': meta.get('clause_count'),
                    },
                ),
                message=(
                    'In-process FOL prover found no contradiction against the '
                    'proposal; the LKB invariants hold.'
                ),
            )

        if verdict == 'fail':
            violated, message, premises = self._classify_unsat(request)
            return SolverResponse(
                result='fail',
                derived_facts=(),
                violated_rule=violated,
                message=message,
                proof_trace=(
                    {
                        'rule': violated,
                        'premises': list(premises),
                        'conclusion': (
                            f'TPTP prover derived $false from the proposal '
                            f'(target={request.target_task_id}, '
                            f'status={request.target_status}).'
                        ),
                        'solverVersion': self.version,
                        'clauseCount': meta.get('clause_count'),
                    },
                ),
            )

        # ``unknown``: saturation cap hit or some other inconclusive
        # outcome. Surface as ``unknown`` so the pipeline treats it as
        # uncertain rather than fail.
        return SolverResponse(
            result='unknown',
            message='In-process FOL prover could not decide inside the budget.',
            error_info={
                'reason': str(meta.get('reason', 'no_decision')),
                'clause_count': meta.get('clause_count'),
            },
        )

    @staticmethod
    def _classify_unsat(
        request: SolverRequest,
    ) -> tuple[str, str, tuple[str, ...]]:
        """Map a refutation back to a recognisable Layer-1 rule.

        The classification mirrors the Layer-4 / Layer-3 helpers so the
        adapter stack produces consistent rule codes for the same
        snapshot, regardless of which backend discovered the violation.
        """
        target = request.target_task_id
        target_status = request.target_status
        snapshot = request.snapshot
        if target is not None and target not in snapshot.normalized_tasks:
            return (
                'LKB-TRANSITION-001',
                f'Task {target} is not present in the current snapshot.',
                (f'Task({target})',),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.cycle_task_ids
        ):
            cycle = tuple(sorted(snapshot.cycle_task_ids))
            return (
                'R-006',
                f'Task {target} is part of a dependency cycle '
                f'({{{", ".join(cycle)}}}) and cannot enter in_progress.',
                tuple(f'Cycle({t})' for t in cycle),
            )
        if (
            target is not None
            and target_status == 'in_progress'
            and target in snapshot.blocked_ids
        ):
            blockers = tuple(
                sorted(
                    b for b in snapshot.blocked_by.get(target, ())
                    if b not in snapshot.completed_ids
                )
            )
            return (
                'R-002',
                f'Task {target} cannot enter in_progress because its '
                f'active blockers remain: {", ".join(blockers) or "<unknown>"}.',
                tuple(f'Requires({b}, {target})' for b in blockers),
            )
        if (
            request.strict_acceptance
            and target is not None
            and target_status == 'completed'
            and not request.acceptance_proof_present
        ):
            return (
                'R-005',
                f'Task {target} requires an acceptance proof in strict mode.',
                (
                    f'StrictAcceptance({target})',
                    f'Not(HasAcceptanceProof({target}))',
                ),
            )
        return (
            'ATP-UNSAT',
            'TPTP prover proved the proposal unsatisfiable; no Layer-1 rule matched.',
            ('Snapshot facts + Layer-1 FOL invariants + Proposal',),
        )


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def default_adapters() -> tuple[SolverAdapter, ...]:
    """Return the default adapter set: Layer 1 always, optional solvers if present."""
    return (Layer1SolverAdapter(),)


def all_adapters() -> tuple[SolverAdapter, ...]:
    """Return every known adapter, including optional ones that may be unavailable."""
    return (
        Layer1SolverAdapter(),
        DatalogSolverAdapter(),
        ClingoSolverAdapter(),
        Z3SolverAdapter(),
        AtpTptpSolverAdapter(),
    )


def extended_adapters() -> tuple[SolverAdapter, ...]:
    """Return the default set with every available optional backend appended.

    Unlike :func:`default_adapters`, this factory probes the environment at
    call time so freshly-installed optional dependencies are picked up
    without re-import. The ordering is deterministic — Layer 1 is always
    first, the optional backends follow in the order they are advertised by
    :func:`all_adapters`. Unavailable adapters (e.g. when ``z3-solver`` is
    not installed) are silently filtered out.
    """
    adapters: list[SolverAdapter] = [Layer1SolverAdapter()]
    from .atp import Mace4SolverAdapter, Prover9SolverAdapter, VampireSolverAdapter

    for adapter in (
        DatalogSolverAdapter(),
        ClingoSolverAdapter(),
        Z3SolverAdapter(),
        AtpTptpSolverAdapter(),
        VampireSolverAdapter(),
        Prover9SolverAdapter(),
        Mace4SolverAdapter(),
    ):
        if adapter.available():
            adapters.append(adapter)
    return tuple(adapters)


__all__ = [
    'AtpTptpSolverAdapter',
    'ClingoSolverAdapter',
    'DatalogSolverAdapter',
    'Layer1SolverAdapter',
    'SolverAdapter',
    'SolverRequest',
    'SolverResponse',
    'SolverResult',
    'Z3SolverAdapter',
    'all_adapters',
    'default_adapters',
    'encode_solver_facts',
    'encode_solver_literal',
    'extended_adapters',
]  # noqa: E501
