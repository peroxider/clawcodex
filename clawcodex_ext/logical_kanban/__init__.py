"""Logical Kanban agent-loop foundation."""

from __future__ import annotations

from .adapters import (
    maybe_commit_task_update,
    maybe_commit_todo_write,
    prepare_task_change,
    prepare_todo_write,
)
from .commit_gate_fuzzy import (
    FUZZY_THRESHOLD_MINOR,
    aggregate_world_results,
    commit_gate_fuzzy_check,
)
from .fuzzy_types import (
    AggregationAction,
    AggregationDecision,
    AggregationStrategy,
    Ambiguity,
    AmbiguityKind,
    AmbiguityReport,
    Assumption,
    AssumptionSource,
    Clarification,
    ClarificationAction,
    CommitDecision,
    DetectionMethod,
    Interpretation,
    MultiWorldResult,
    Severity,
    ValidationResultForWorld,
    World,
    WorldValidationResult,
)
from .glossary import BUILT_IN_GLOSSARY, Glossary, GlossaryEntry
from .ambiguity_detector import AmbiguityDetector
from .fuzzy_patterns import BUILT_IN_PATTERN_LIBRARY, DomainConstraint, FuzzyPattern, FuzzyPatternLibrary
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
from .multiworld_validator import MultiWorldValidator
from .predicate_extractor import (
    PredicateExtraction,
    extract_predicates,
    validate_assertion,
)
from .rule_engine import Layer1RuleEngine, RuleEngineResult, evaluate_rules
from .runtime import LogicalKanbanRuntime, get_logical_kanban
from .service import LogicalKanbanService
from .truth_maintenance import (
    AssumptionRecord,
    AssertionRecord,
    TruthMaintenanceSystem,
)
from .types import (
    CommitResult,
    FactsSnapshot,
    Proposal,
    ProposedChange,
    RepairSuggestion,
    ValidationIssue,
    ValidationRun,
)
from .world_generator import WorldGenerator

__all__ = [
    'AggregationAction',
    'AggregationDecision',
    'AggregationStrategy',
    'Ambiguity',
    'AmbiguityDetector',
    'AmbiguityKind',
    'AmbiguityReport',
    'AssertionKind',
    'AssertionRole',
    'Assumption',
    'AssumptionRecord',
    'AssumptionSource',
    'BUILT_IN_GLOSSARY',
    'BUILT_IN_PATTERN_LIBRARY',
    'CanonicalAssertion',
    'Clarification',
    'ClarificationAction',
    'CommitDecision',
    'CommitResult',
    'DetectionMethod',
    'DomainConstraint',
    'FactsSnapshot',
    'FUZZY_THRESHOLD_MINOR',
    'FuzzyPattern',
    'FuzzyPatternLibrary',
    'Glossary',
    'GlossaryEntry',
    'IROperation',
    'IRNode',
    'IRPredicate',
    'IRVariable',
    'Interpretation',
    'Layer1RuleEngine',
    'LogicalKanbanRuntime',
    'LogicalKanbanService',
    'MultiWorldResult',
    'MultiWorldValidator',
    'PredicateExtraction',
    'Proposal',
    'ProposedChange',
    'Quantifier',
    'RepairSuggestion',
    'RuleEngineResult',
    'SCHEMA_VERSION',
    'Severity',
    'TruthMaintenanceSystem',
    'ValidationIssue',
    'ValidationResultForWorld',
    'ValidationRun',
    'World',
    'WorldGenerator',
    'WorldValidationResult',
    'aggregate_world_results',
    'and_',
    'assertion_hash',
    'canonical_hash',
    'canonical_json',
    'commit_gate_fuzzy_check',
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
