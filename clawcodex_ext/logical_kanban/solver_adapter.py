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

    MVP stub: reports availability only when ``souffle`` is on ``PATH``.  Full
    compilation from the canonical IR to Datalog facts/rules is left for a
    later iteration.
    """

    @property
    def name(self) -> str:
        return 'datalog-souffle'

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
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='Soufflé Datalog engine is not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        # F-139: encode facts so raw NL never reaches the external solver.
        _encoded = encode_solver_facts(request)
        return SolverResponse(
            result='unknown',
            message='Datalog compilation is not implemented in this MVP build.',
            error_info={'reason': 'not_implemented'},
        )


class ClingoSolverAdapter(SolverAdapter):
    """Optional Layer-3 ASP/clingo adapter.

    MVP stub: reports availability only when the ``clingo`` Python package is
    importable.  Full ASP encoding of the IR is left for a later iteration.
    """

    @property
    def name(self) -> str:
        return 'asp-clingo'

    @property
    def version(self) -> str:
        try:
            import clingo

            return getattr(clingo, '__version__', 'unknown')
        except Exception:  # pragma: no cover
            return 'unavailable'

    def available(self) -> bool:
        try:
            import clingo  # noqa: F401

            return True
        except Exception:
            return False

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='clingo Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        # F-139: encode facts so raw NL never reaches the external solver.
        _encoded = encode_solver_facts(request)
        return SolverResponse(
            result='unknown',
            message='ASP/clingo encoding is not implemented in this MVP build.',
            error_info={'reason': 'not_implemented'},
        )


class Z3SolverAdapter(SolverAdapter):
    """Optional Layer-4 SMT/Z3 adapter.

    MVP stub: reports availability only when the ``z3-solver`` package is
    importable.  Full SMT-LIB encoding of the IR is left for a later iteration.
    """

    @property
    def name(self) -> str:
        return 'smt-z3'

    @property
    def version(self) -> str:
        try:
            import z3

            return getattr(z3, 'get_version_string', lambda: 'unknown')()
        except Exception:  # pragma: no cover
            return 'unavailable'

    def available(self) -> bool:
        try:
            import z3  # noqa: F401

            return True
        except Exception:
            return False

    def solve(
        self,
        request: SolverRequest,
        *,
        timeout_seconds: float = 30.0,
    ) -> SolverResponse:
        if not self.available():
            return SolverResponse(
                result='unknown',
                message='Z3 Python bindings are not installed.',
                error_info={'reason': 'engine_unavailable'},
            )
        # F-139: encode facts so raw NL never reaches the external solver.
        _encoded = encode_solver_facts(request)
        return SolverResponse(
            result='unknown',
            message='SMT-LIB encoding is not implemented in this MVP build.',
            error_info={'reason': 'not_implemented'},
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
    )


__all__ = [
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
]
