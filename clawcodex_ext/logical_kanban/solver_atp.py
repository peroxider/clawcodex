"""In-process first-order ATP for the F-138 Layer-5 ``atp-tptp`` adapter.

This is **not** a general-purpose FOL theorem prover. It is a focused,
hand-rolled saturation prover restricted to the LKB Horn-ish fragment:

* only predicate symbols (no function symbols),
* only ground constants from the snapshot's task universe,
* universal quantifiers are eagerly grounded over that universe,
* no equality, no arithmetic, no theory reasoning.

That covers every formula the F-138 issue tracker lists for Layer-2/3/4/5
mirroring (R-002, R-005, R-006, LKB-TRANSITION-001), which is the entire
Layer-1 MVP rule set expressed as FOL. Outside that fragment the prover
returns ``unknown`` — by design, mirroring the conservative aggregation
policy that governs every other F-138 backend.

The encoding contract is deliberately close to TPTP FOF so that this
module can be swapped for ``vampire``/``eprover`` via subprocess later
without changing the adapter surface. The :class:`AtpTptpSolverAdapter`
emits the same axioms in TPTP syntax for human/audit inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .solver_adapter import SolverRequest
    from .types import FactsSnapshot


# ---------------------------------------------------------------------------
# Term / literal / clause
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Term:
    """A first-order term. For the LKB fragment only constants appear."""

    name: str  # constants only — variables are not used after grounding

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f'Term name must be a non-empty string, got {self.name!r}')


@dataclass(frozen=True, slots=True)
class Literal:
    """A signed predicate atom with ground arguments.

    ``positive=False`` means negation. The predicate name and argument
    arity are encoded together (``predicate_name + '/' + arity`` in the
    ``predicate`` field) so two literals only unify when they share both
    name and arity.
    """

    predicate: str  # e.g. ``blocked/1``
    args: tuple[Term, ...]
    positive: bool

    def negated(self) -> 'Literal':
        return Literal(self.predicate, self.args, not self.positive)

    def complement(self, other: 'Literal') -> bool:
        """Return True if ``self`` and ``other`` are complementary literals."""
        return (
            self.predicate == other.predicate
            and self.args == other.args
            and self.positive != other.positive
        )


@dataclass(frozen=True, slots=True)
class Clause:
    """A disjunction of literals. Empty clause represents ``$false``."""

    literals: frozenset[Literal] = field(default_factory=frozenset)

    def __len__(self) -> int:
        return len(self.literals)

    @property
    def is_empty(self) -> bool:
        return not self.literals

    def is_tautology(self) -> bool:
        for lit in self.literals:
            if lit.negated() in self.literals:
                return True
        return False

    def subsumes(self, other: 'Clause') -> bool:
        """A clause subsumes another iff its literal set is a subset.

        Tautological and empty clauses are handled specially.
        """
        if self.is_empty:
            return other.is_empty
        if other.is_empty:
            return False
        return self.literals.issubset(other.literals)


# ---------------------------------------------------------------------------
# Builder helpers — keep the adapter concise.
# ---------------------------------------------------------------------------


def pred(name: str, *args: str, positive: bool = True) -> Literal:
    """Build a Literal from a predicate name and string arguments."""
    return Literal(
        predicate=f'{name}/{len(args)}',
        args=tuple(Term(a) for a in args),
        positive=positive,
    )


def clause(*literals: Literal) -> Clause:
    """Build a clause from literals, dropping tautologies."""
    raw = frozenset(literals)
    c = Clause(raw)
    if c.is_tautology():
        # Tautological clauses add no information; represent as the
        # universally-true clause (``{}`` is the empty clause = $false,
        # so we use a sentinel with a single tautological literal that
        # the prover drops before saturation).
        return Clause(frozenset({Literal('__tautology__/0', (), True)}))
    return c


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_pair(c1: Clause, c2: Clause) -> Iterable[Clause]:
    """Apply binary resolution on every complementary literal pair.

    Yields each resolvent. Variable binding is a no-op because the
    prover's fragment is already ground — complementary literals must
    match exactly on predicate and arguments for resolution to fire.
    """
    for lit1 in c1.literals:
        for lit2 in c2.literals:
            if lit1.complement(lit2):
                new_lits = (c1.literals - {lit1}) | (c2.literals - {lit2})
                if any(lit.predicate == '__tautology__/0' for lit in new_lits):
                    continue
                resolvent = Clause(frozenset(new_lits))
                if not resolvent.is_tautology():
                    yield resolvent


def saturate(
    initial: Iterable[Clause],
    *,
    max_new: int = 4096,
) -> tuple[bool, int]:
    """Run binary resolution to saturation.

    Returns ``(derived_false, total_clauses)``. ``derived_false`` is
    True when the empty clause (representing ``$false``) is derivable
    from the initial clause set; in that case the input is unsatisfiable
    and the LKB proposal should be rejected.

    The saturation loop applies the given-clause algorithm with a hard
    cap on new clauses generated per call so a runaway snapshot cannot
    hang the solver. Anything past the cap returns ``derived_false=False``
    which the caller maps to ``unknown`` (conservative default).
    """
    base: set[Clause] = {c for c in initial if not c.is_empty}
    # Drop tautologies up front — they cannot contribute to refutation.
    base = {c for c in base if not c.is_tautology()}

    if any(c.is_empty for c in initial):
        return True, len(base)

    seen: set[Clause] = set(base)
    new_count = 0
    worklist = list(base)
    while worklist:
        # Pick the smallest clause first — heuristic for early refutation.
        worklist.sort(key=len)
        c1 = worklist.pop(0)
        for c2 in list(seen):
            if c1 is c2:
                continue
            for resolvent in _resolve_pair(c1, c2):
                if resolvent.is_empty:
                    return True, len(seen) + 1
                if resolvent in seen:
                    continue
                seen.add(resolvent)
                worklist.append(resolvent)
                new_count += 1
                if new_count >= max_new:
                    return False, len(seen)
    return False, len(seen)


# ---------------------------------------------------------------------------
# LKB fragment encoder
# ---------------------------------------------------------------------------


# The four invariant predicates the adapter encodes as FOL clauses. Kept
# here so the adapter and the tests can refer to them by name.
INVARIANT_PREDICATES = (
    'task/1',
    'do_proposal/1',
    'complete_proposal/1',
    'reopen_proposal/1',
    'blocked/1',
    'in_cycle/1',
    'has_acceptance_proof/1',
    'strict_acceptance/0',
)


def task_constants(snapshot_tasks: Iterable[str]) -> tuple[str, ...]:
    """Return the closed-world task universe for grounding."""
    return tuple(sorted(set(snapshot_tasks)))


def encode_lkb_axioms(
    *,
    constants: tuple[str, ...],
    blocked_ids: frozenset[str],
    cycle_ids: frozenset[str],
    has_proof_ids: frozenset[str],
    strict_acceptance: bool,
) -> list[Clause]:
    """Return the invariant clauses for a snapshot, ground over ``constants``.

    Each universal formula is instantiated for every task identifier in
    the closed-world universe, producing ground propositional clauses
    that :func:`saturate` can refute.
    """
    clauses: list[Clause] = []

    # R-002: blocked cannot enter in_progress.
    # FOL: ∀X. ¬(do_proposal(X) ∧ blocked(X))
    # CNF: ¬do_proposal(X) ∨ ¬blocked(X)
    for c in constants:
        clauses.append(
            clause(
                pred('do_proposal', c, positive=False),
                pred('blocked', c, positive=False),
            )
        )

    # R-006: cycle cannot enter in_progress.
    # FOL: ∀X. ¬(do_proposal(X) ∧ in_cycle(X))
    # CNF: ¬do_proposal(X) ∨ ¬in_cycle(X)
    for c in constants:
        clauses.append(
            clause(
                pred('do_proposal', c, positive=False),
                pred('in_cycle', c, positive=False),
            )
        )

    # R-005: strict-acceptance completion requires proof.
    # FOL: ∀X. ¬(complete_proposal(X) ∧ strict_acceptance ∧ ¬has_acceptance_proof(X))
    # CNF: ¬complete_proposal(X) ∨ ¬strict_acceptance ∨ has_acceptance_proof(X)
    if strict_acceptance:
        for c in constants:
            clauses.append(
                clause(
                    pred('complete_proposal', c, positive=False),
                    pred('strict_acceptance', positive=False),
                    pred('has_acceptance_proof', c, positive=True),
                )
            )

    # LKB-TRANSITION-001: target must be a known task.
    # FOL: ∀X. ¬(do_proposal(X) ∧ ¬task(X))  — same for complete/reopen.
    for c in constants:
        clauses.append(
            clause(
                pred('do_proposal', c, positive=False),
                pred('task', c, positive=True),
            )
        )
        clauses.append(
            clause(
                pred('complete_proposal', c, positive=False),
                pred('task', c, positive=True),
            )
        )
        clauses.append(
            clause(
                pred('reopen_proposal', c, positive=False),
                pred('task', c, positive=True),
            )
        )

    return clauses


def encode_lkb_facts(
    *,
    constants: tuple[str, ...],
    blocked_ids: frozenset[str],
    cycle_ids: frozenset[str],
    has_proof_ids: frozenset[str],
    strict_acceptance: bool,
    completed_ids: frozenset[str],
    proposal_target: str | None,
    proposal_status: str | None,
    snapshot_task_ids: frozenset[str] | None = None,
) -> list[Clause]:
    """Return unit-clause facts to seed the saturation.

    * ``task(c)`` for every constant in ``snapshot_task_ids``,
      ``¬task(c)`` for every constant outside it. Defaults to closed-
      world (every constant is a task) when ``snapshot_task_ids`` is
      not provided.
    * ``blocked(c)`` for snapshot-blocked ids, ``¬blocked(c)`` for others
      in the universe (closed-world assumption on ``blocked``).
    * Same for ``in_cycle`` and ``has_acceptance_proof``.
    * ``strict_acceptance.`` or ``¬strict_acceptance.`` depending on the
      request flag.
    * The proposal atoms (``do_proposal(target)`` / ``complete_proposal``
      / ``reopen_proposal``) when both target and status are provided.
    """
    clauses: list[Clause] = []

    snapshot_ids = (
        snapshot_task_ids if snapshot_task_ids is not None else frozenset(constants)
    )

    # task(c) / ¬task(c)
    for c in constants:
        clauses.append(clause(pred('task', c, positive=(c in snapshot_ids))))

    # blocked(c) / not blocked(c)
    for c in constants:
        if c in blocked_ids:
            clauses.append(clause(pred('blocked', c, positive=True)))
        else:
            clauses.append(clause(pred('blocked', c, positive=False)))

    # in_cycle(c) / not in_cycle(c)
    for c in constants:
        if c in cycle_ids:
            clauses.append(clause(pred('in_cycle', c, positive=True)))
        else:
            clauses.append(clause(pred('in_cycle', c, positive=False)))

    # has_acceptance_proof(c) / not has_acceptance_proof(c)
    for c in constants:
        if c in has_proof_ids:
            clauses.append(clause(pred('has_acceptance_proof', c, positive=True)))
        else:
            clauses.append(clause(pred('has_acceptance_proof', c, positive=False)))

    # strict_acceptance flag
    if strict_acceptance:
        clauses.append(clause(pred('strict_acceptance', positive=True)))
    else:
        clauses.append(clause(pred('strict_acceptance', positive=False)))

    # Proposal atoms (the conjecture under test)
    if proposal_target is not None and proposal_status is not None:
        if proposal_status == 'in_progress':
            clauses.append(clause(pred('do_proposal', proposal_target, positive=True)))
        elif proposal_status == 'completed':
            clauses.append(clause(pred('complete_proposal', proposal_target, positive=True)))
        elif proposal_status == 'pending':
            clauses.append(clause(pred('reopen_proposal', proposal_target, positive=True)))
        # deleted / unknown statuses are silently dropped: the
        # invariant clauses won't fire and the prover reports SAT
        # (mirroring the Layer-1 engine's neutral behaviour).

    return clauses


def prove_lkb_request(
    *,
    constants: tuple[str, ...],
    blocked_ids: frozenset[str],
    cycle_ids: frozenset[str],
    has_proof_ids: frozenset[str],
    completed_ids: frozenset[str],
    strict_acceptance: bool,
    proposal_target: str | None,
    proposal_status: str | None,
    snapshot_task_ids: frozenset[str] | None = None,
    max_new_clauses: int = 4096,
) -> tuple[str, dict[str, object]]:
    """Run the prover end-to-end for one LKB request.

    Returns ``(verdict, meta)`` where ``verdict`` is one of
    ``'pass' | 'fail' | 'unknown'``. ``meta`` carries debugging info
    (``clause_count``, ``reason``) the adapter may surface in the
    proof trace.

    ``snapshot_task_ids`` is the set of task identifiers that are
    actually present in the LKB snapshot. ``constants`` is the closed-
    world universe used for grounding. When ``proposal_target`` falls
    outside that universe (e.g. an unknown task id), the prover adds
    ``proposal_target`` to the universe with ``¬task(target)`` asserted
    so the LKB-TRANSITION-001 invariant fires correctly.
    """
    universe: tuple[str, ...] = tuple(sorted(set(constants)))
    if proposal_target is not None and proposal_target not in universe:
        universe = universe + (proposal_target,)

    snapshot_ids = snapshot_task_ids or frozenset(constants)

    axioms = encode_lkb_axioms(
        constants=universe,
        blocked_ids=blocked_ids,
        cycle_ids=cycle_ids,
        has_proof_ids=has_proof_ids,
        strict_acceptance=strict_acceptance,
    )
    facts = encode_lkb_facts(
        constants=universe,
        blocked_ids=blocked_ids,
        cycle_ids=cycle_ids,
        has_proof_ids=has_proof_ids,
        strict_acceptance=strict_acceptance,
        completed_ids=completed_ids,
        proposal_target=proposal_target,
        proposal_status=proposal_status,
        snapshot_task_ids=snapshot_ids,
    )

    derived_false, total = saturate(facts + axioms, max_new=max_new_clauses)
    if total >= max_new_clauses:
        return 'unknown', {
            'reason': 'saturation_cap',
            'clause_count': total,
            'cap': max_new_clauses,
        }
    if derived_false:
        return 'fail', {'reason': 'refutation', 'clause_count': total}
    return 'pass', {'reason': 'saturation_silent', 'clause_count': total}


# ---------------------------------------------------------------------------
# TPTP FOF emitter — emits the same axioms in TPTP syntax for audit/debug.
# ---------------------------------------------------------------------------


def _tptp_atom(literal: Literal) -> str:
    """Render a literal as a TPTP ``$true``/``$false`` predicate atom.

    Arguments are sanitised via ``encode_solver_literal`` and wrapped in
    TPTP double-quoted atoms so the emitted program is well-formed even
    for adversarial task identifiers.
    """
    from .solver_adapter import encode_solver_literal

    if literal.predicate == '__tautology__/0':
        return '$true'
    name, _, arity_str = literal.predicate.partition('/')
    arity = int(arity_str)
    args = ', '.join(encode_solver_literal(a.name) for a in literal.args)
    atom = f'{name}({args})' if arity else name
    # TPTP forbids ``$`` inside atom names; wrap in double quotes so the
    # encoded literal (which may contain underscores/digits/etc.) is a
    # TPTP-distinct-object.
    quoted = f'"{atom}"'
    return quoted if literal.positive else f'~{quoted}'


def emit_tptp_program(
    *,
    constants: tuple[str, ...],
    blocked_ids: frozenset[str],
    cycle_ids: frozenset[str],
    has_proof_ids: frozenset[str],
    strict_acceptance: bool,
    proposal_target: str | None,
    proposal_status: str | None,
) -> str:
    """Render the LKB fragment as a TPTP FOF program for audit/debug.

    The output is well-formed TPTP and can be fed directly to ``vampire``
    or ``eprover`` if either is installed; the in-process prover does
    not parse TPTP — it builds the same clause set directly.
    """
    from .solver_adapter import encode_solver_literal

    lines: list[str] = ['% Generated by lkb-atp-tptp']
    counter = 0

    def next_name(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f'{prefix}_{counter}'

    # Snapshot facts (axioms).
    for c in constants:
        lines.append(
            f"fof({next_name('task')}, axiom, { _tptp_atom(pred('task', c, positive=True)) } )."
        )

    for c in constants:
        lit = pred('blocked', c, positive=(c in blocked_ids))
        lines.append(f'fof({next_name("blocked")}, axiom, { _tptp_atom(lit) } ).')

    for c in constants:
        lit = pred('in_cycle', c, positive=(c in cycle_ids))
        lines.append(f'fof({next_name("cycle")}, axiom, { _tptp_atom(lit) } ).')

    for c in constants:
        lit = pred('has_acceptance_proof', c, positive=(c in has_proof_ids))
        lines.append(
            f'fof({next_name("proof")}, axiom, { _tptp_atom(lit) } ).'
        )

    sa_atom = pred('strict_acceptance', positive=strict_acceptance)
    lines.append(
        f'fof({next_name("strict")}, axiom, { _tptp_atom(sa_atom) } ).'
    )

    # Invariant rules (axioms). Rendered as universally quantified FOF
    # so the emitted TPTP is faithful to the LKB rule shape; the
    # in-process prover grounds these eagerly.
    for c in constants:
        lines.append(
            f'fof({next_name("r002")}, axiom, '
            f'! [X] : ({ _tptp_atom(pred("do_proposal", c, positive=False)) } | '
            f'{ _tptp_atom(pred("blocked", c, positive=False)) }) ).'
        )
    for c in constants:
        lines.append(
            f'fof({next_name("r006")}, axiom, '
            f'! [X] : ({ _tptp_atom(pred("do_proposal", c, positive=False)) } | '
            f'{ _tptp_atom(pred("in_cycle", c, positive=False)) }) ).'
        )
    if strict_acceptance:
        for c in constants:
            lines.append(
                f'fof({next_name("r005")}, axiom, '
                f'! [X] : ('
                f'{ _tptp_atom(pred("complete_proposal", c, positive=False)) } | '
                f'{ _tptp_atom(pred("strict_acceptance", positive=False)) } | '
                f'{ _tptp_atom(pred("has_acceptance_proof", c, positive=True)) } '
                f') ).'
            )

    # Proposal as conjecture — a real ATP would attempt to prove it.
    if proposal_target is not None and proposal_status is not None:
        safe_target = encode_solver_literal(proposal_target)
        if proposal_status == 'in_progress':
            atom = f'"do_proposal({safe_target})"'
        elif proposal_status == 'completed':
            atom = f'"complete_proposal({safe_target})"'
        elif proposal_status == 'pending':
            atom = f'"reopen_proposal({safe_target})"'
        else:
            atom = '$true'
        lines.append(
            f'fof({next_name("conjecture")}, conjecture, {atom} ).'
        )

    return '\n'.join(lines) + '\n'


def build_tptp_program(snapshot: 'FactsSnapshot', request: 'SolverRequest') -> str:
    """Build a replayable TPTP FOF program for an LKB solver request.

    The program is deliberately side-effect-free and uses only canonical
    snapshot fields plus proposal metadata from ``request``. User-controlled
    strings are routed through :func:`encode_solver_literal` before they are
    embedded as TPTP distinct objects.
    """
    from .solver_adapter import encode_solver_literal

    task_ids = tuple(sorted(snapshot.normalized_tasks))
    universe = tuple(
        sorted(set(task_ids) | ({request.target_task_id} if request.target_task_id else set()))
    )
    has_proof_ids = frozenset(
        task_id
        for task_id, task in snapshot.normalized_tasks.items()
        if (task.get('metadata') or {}).get('lkb', {}).get('acceptance_proof')
    )

    lines: list[str] = [
        '% Generated by lkb-build-tptp-program',
        '% solver_syntax: tptp-fof',
    ]
    counter = 0

    def next_name(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f'{prefix}_{counter}'

    def obj(value: str) -> str:
        return f'"{encode_solver_literal(value)}"'

    def atom(name: str, *args: str) -> str:
        if not args:
            return name
        return f'{name}({", ".join(obj(arg) for arg in args)})'

    for task_id in universe:
        is_known = task_id in snapshot.normalized_tasks
        lines.append(
            f'fof({next_name("task")}, axiom, '
            f'{"~" if not is_known else ""}{atom("task", task_id)} ).'
        )
        if is_known:
            task = snapshot.normalized_tasks[task_id]
            subject = str(task.get('subject', task_id))
            lines.append(
                f'fof({next_name("task_subject")}, axiom, '
                f'task_subject({obj(task_id)}, {obj(subject)}) ).'
            )

    for task_id in universe:
        lines.append(
            f'fof({next_name("blocked")}, axiom, '
            f'{"~" if task_id not in snapshot.blocked_ids else ""}{atom("blocked", task_id)} ).'
        )
        lines.append(
            f'fof({next_name("cycle")}, axiom, '
            f'{"~" if task_id not in snapshot.cycle_task_ids else ""}{atom("in_cycle", task_id)} ).'
        )
        lines.append(
            f'fof({next_name("acceptance")}, axiom, '
            f'{"~" if task_id not in has_proof_ids else ""}'
            f'{atom("has_acceptance_proof", task_id)} ).'
        )

    for task_id, blockers in sorted(snapshot.blocked_by.items()):
        for blocker in blockers:
            lines.append(
                f'fof({next_name("requires")}, axiom, {atom("requires", blocker, task_id)} ).'
            )

    lines.extend(
        [
            'fof(r002_blocked_no_doing, axiom, '
            '! [T] : ((blocked(T) & do_proposal(T)) => $false) ).',
            'fof(r006_cycle_no_doing, axiom, '
            '! [T] : ((in_cycle(T) & do_proposal(T)) => $false) ).',
            'fof(lkb_transition_known_task_do, axiom, '
            '! [T] : ((do_proposal(T) & ~task(T)) => $false) ).',
            'fof(lkb_transition_known_task_complete, axiom, '
            '! [T] : ((complete_proposal(T) & ~task(T)) => $false) ).',
            'fof(lkb_transition_known_task_reopen, axiom, '
            '! [T] : ((reopen_proposal(T) & ~task(T)) => $false) ).',
        ]
    )
    if request.strict_acceptance:
        lines.append(
            'fof(r005_done_requires_acceptance_proof, axiom, '
            '! [T] : ((complete_proposal(T) & ~has_acceptance_proof(T)) => $false) ).'
        )

    if request.target_task_id is not None and request.target_status is not None:
        if request.target_status == 'in_progress':
            proposal_atom = atom('do_proposal', request.target_task_id)
        elif request.target_status == 'completed':
            proposal_atom = atom('complete_proposal', request.target_task_id)
        elif request.target_status == 'pending':
            proposal_atom = atom('reopen_proposal', request.target_task_id)
        else:
            proposal_atom = '$true'
        lines.append(f'fof({next_name("proposal")}, conjecture, {proposal_atom} ).')

    return '\n'.join(lines) + '\n'


__all__ = [
    'Clause',
    'build_tptp_program',
    'INVARIANT_PREDICATES',
    'Literal',
    'Term',
    'clause',
    'emit_tptp_program',
    'encode_lkb_axioms',
    'encode_lkb_facts',
    'pred',
    'prove_lkb_request',
    'saturate',
    'task_constants',
]
