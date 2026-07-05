"""Tests for F-131 Canonical IR and Glossary."""

from __future__ import annotations

import pytest

from clawcodex_ext.logical_kanban import (
    BUILT_IN_GLOSSARY,
    CanonicalAssertion,
    Glossary,
    GlossaryEntry,
    PredicateExtraction,
    and_,
    assertion_hash,
    canonical_hash,
    canonical_json,
    extract_predicates,
    implies,
    make_canonical,
    not_,
    or_,
    pred,
    render_assertion,
    render_proof_trace,
    validate_assertion,
)


def test_canonical_assertion_to_dict_matches_spec():
    assertion = make_canonical(
        role='axiom',
        kind='prerequisite',
        quantifier='forall',
        vars=(
            {'name': 'A', 'type': 'Task'},
            {'name': 'B', 'type': 'Task'},
        ),
        body=implies(
            pred('Requires', 'A', 'B'),
            pred('Blocks', 'A', 'B'),
        ),
    )
    assert assertion.to_dict() == {
        'schema_version': '1.0',
        'role': 'axiom',
        'kind': 'prerequisite',
        'quantifier': 'forall',
        'vars': [{'name': 'A', 'type': 'Task'}, {'name': 'B', 'type': 'Task'}],
        'body': {
            'op': 'implies',
            'args': [
                {'pred': 'Requires', 'args': ['A', 'B']},
                {'pred': 'Blocks', 'args': ['A', 'B']},
            ],
        },
    }


def test_builtin_glossary_contains_required_predicates():
    required = {
        'Task',
        'Status',
        'Pending',
        'Ready',
        'Doing',
        'Done',
        'Blocked',
        'Requires',
        'Blocks',
        'CanMoveTo',
        'Permitted',
        'HasAcceptanceProof',
        'Contradicts',
        'Assumes',
        'DerivedFrom',
        'Active',
        'Invalid',
    }
    assert required.issubset(BUILT_IN_GLOSSARY.predicate_names())


def test_same_ir_produces_stable_hash_across_runs():
    assertion = make_canonical(
        role='axiom',
        kind='prerequisite',
        body=implies(
            pred('Requires', 'A', 'B'),
            pred('Blocks', 'A', 'B'),
        ),
        quantifier='forall',
        vars=(
            {'name': 'A', 'type': 'Task'},
            {'name': 'B', 'type': 'Task'},
        ),
    )
    first = assertion_hash(assertion)
    second = assertion_hash(assertion)
    assert first == second
    assert first.startswith('sha256:')


def test_hash_covers_canonical_json_not_presentation():
    assertion = make_canonical(
        role='axiom',
        kind='prerequisite',
        body=implies(
            pred('Requires', 'A', 'B'),
            pred('Blocks', 'A', 'B'),
        ),
    )
    assert assertion_hash(assertion) == canonical_hash(assertion.to_dict())


def test_predicate_extraction_rejects_unknown_predicate():
    assertion = make_canonical(
        role='axiom',
        kind='consistency',
        body=pred('UnknownPredicate', 'X'),
    )
    result = validate_assertion(assertion, BUILT_IN_GLOSSARY)
    assert result.status == 'needs_glossary_review'
    assert 'UnknownPredicate' in result.unknown
    assert 'UnknownPredicate' in result.predicates


def test_predicate_extraction_accepts_registered_predicates():
    assertion = make_canonical(
        role='axiom',
        kind='prerequisite',
        body=implies(
            pred('Requires', 'A', 'B'),
            pred('Blocks', 'A', 'B'),
        ),
    )
    result = validate_assertion(assertion, BUILT_IN_GLOSSARY)
    assert result.status == 'valid'
    assert result.unknown == frozenset()
    assert {'Requires', 'Blocks'}.issubset(result.predicates)


def test_predicate_extraction_recurses_through_operations():
    assertion = make_canonical(
        role='derived',
        kind='state_transition',
        body=and_(
            pred('Ready', 'T'),
            implies(
                pred('CanMoveTo', 'T', 'in_progress'),
                pred('Permitted', 'T', 'in_progress'),
            ),
        ),
    )
    predicates = extract_predicates(assertion.body)
    assert predicates == {'Ready', 'CanMoveTo', 'Permitted'}


def test_renderer_dependency_blocking_rule():
    assertion = make_canonical(
        role='axiom',
        kind='prerequisite',
        quantifier='forall',
        vars=(
            {'name': 'A', 'type': 'Task'},
            {'name': 'B', 'type': 'Task'},
        ),
        body=implies(
            pred('Requires', 'A', 'B'),
            pred('Blocks', 'A', 'B'),
        ),
    )
    text = render_assertion(assertion, BUILT_IN_GLOSSARY)
    assert text.startswith('For all A:Task, B:Task')
    assert 'Requires(A, B)' in text
    assert 'Blocks(A, B)' in text


def test_renderer_uses_glossary_names():
    assertion = make_canonical(
        role='axiom',
        kind='acceptance',
        body=pred('HasAcceptanceProof', 'T'),
    )
    text = render_assertion(assertion, BUILT_IN_GLOSSARY)
    assert 'HasAcceptanceProof(T)' in text


def test_renderer_compound_operations():
    assertion = make_canonical(
        role='axiom',
        kind='invariant',
        body=and_(
            pred('Task', 'X'),
            not_(pred('Invalid', 'X')),
        ),
    )
    text = render_assertion(assertion)
    assert 'Task(X)' in text
    assert 'it is not the case that Invalid(X)' in text


def test_render_proof_trace():
    trace = {
        'rule': 'LKB-001',
        'premises': ['ActiveBlockers(T) = []'],
        'conclusion': 'CanMoveTo(T, in_progress)',
    }
    text = render_proof_trace(trace)
    assert 'LKB-001' in text
    assert 'ActiveBlockers(T) = []' in text
    assert 'CanMoveTo(T, in_progress)' in text


def test_canonical_json_is_sorted_and_compact():
    value = {'z': 1, 'a': 2, 'nested': {'b': 3, 'a': 4}}
    assert canonical_json(value) == '{"a":2,"nested":{"a":4,"b":3},"z":1}'


def test_glossary_union_and_add():
    custom = Glossary().add(GlossaryEntry(name='CustomPred', category='relation', arity=2))
    combined = BUILT_IN_GLOSSARY.union(custom)
    assert 'CustomPred' in combined
    assert 'Requires' in combined


def test_quantifier_without_vars():
    assertion = make_canonical(
        role='axiom',
        kind='invariant',
        body=pred('Active', 'System'),
    )
    text = render_assertion(assertion)
    assert text.startswith('For all cases')


def test_predicate_extraction_to_dict():
    result = PredicateExtraction(
        predicates=frozenset({'Requires', 'Blocks'}),
        unknown=frozenset(),
        status='valid',
    )
    assert result.to_dict() == {
        'predicates': ['Blocks', 'Requires'],
        'unknown': [],
        'status': 'valid',
    }
