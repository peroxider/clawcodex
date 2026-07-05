"""Logical Kanban agent-loop foundation."""

from __future__ import annotations

from .adapters import (
    maybe_commit_task_update,
    maybe_commit_todo_write,
    prepare_task_change,
    prepare_todo_write,
)
from .glossary import BUILT_IN_GLOSSARY, Glossary, GlossaryEntry
from .ir import (
    SCHEMA_VERSION,
    AssertionKind,
    AssertionRole,
    CanonicalAssertion,
    IROperation,
    IRNode,
    IRPredicate,
    IRVariable,
    Quantifier,
    and_,
    implies,
    make_canonical,
    not_,
    or_,
    pred,
)
from .ir_hash import assertion_hash, canonical_hash, canonical_json
from .ir_renderer import render_assertion, render_node, render_proof_trace
from .predicate_extractor import (
    PredicateExtraction,
    extract_predicates,
    validate_assertion,
)
from .rule_engine import Layer1RuleEngine, RuleEngineResult, evaluate_rules
from .runtime import LogicalKanbanRuntime, get_logical_kanban
from .service import LogicalKanbanService
from .types import (
    CommitResult,
    FactsSnapshot,
    Proposal,
    ProposedChange,
    RepairSuggestion,
    ValidationIssue,
    ValidationRun,
)

__all__ = [
    'AssertionKind',
    'AssertionRole',
    'BUILT_IN_GLOSSARY',
    'CanonicalAssertion',
    'CommitResult',
    'FactsSnapshot',
    'Glossary',
    'GlossaryEntry',
    'IROperation',
    'IRNode',
    'IRPredicate',
    'IRVariable',
    'Layer1RuleEngine',
    'LogicalKanbanRuntime',
    'LogicalKanbanService',
    'PredicateExtraction',
    'Proposal',
    'ProposedChange',
    'Quantifier',
    'RepairSuggestion',
    'RuleEngineResult',
    'SCHEMA_VERSION',
    'ValidationIssue',
    'ValidationRun',
    'and_',
    'assertion_hash',
    'canonical_hash',
    'canonical_json',
    'evaluate_rules',
    'extract_predicates',
    'get_logical_kanban',
    'implies',
    'make_canonical',
    'maybe_commit_task_update',
    'maybe_commit_todo_write',
    'not_',
    'or_',
    'pred',
    'prepare_task_change',
    'prepare_todo_write',
    'render_assertion',
    'render_node',
    'render_proof_trace',
    'validate_assertion',
]
