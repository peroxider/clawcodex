# lkb — Logical Kanban Boards

**lkb** is a standalone Python package for formal task decomposition with rule engines, ATP solvers, and multi-world validation. Originally part of the [ClawCodex](https://gitcode.com/chadwweng/clawcodex) project, it is distributed as an independent package for reuse outside the ClawCodex ecosystem.

## Features

- **Task Decomposition** — Break down a natural-language goal into a validated, dependency-aware task plan
- **Rule Engine** — Enforce task lifecycle rules (R-001..R-006): no cycles, no dangling blockers, no contradictory states
- **ATP Solvers** — Optional automated theorem proving backends (Z3, Prover9, Vampire, Clingo) for formal state-space validation
- **Multi-World Validation** — Explore alternative task states and detect inconsistencies
- **Causal Verification** — Trace cause-effect chains across task transitions
- **LLM Fact Extraction** — Extract structured facts from unstructured context
- **Audit Log** — Full event-sourced audit trail for every proposal, validation, and commit
- **Method Library** — Reusable engineering methods (TDD, exploratory prototyping, etc.) with governance rules
- **Acceptance Templates** — Structured acceptance criteria with proof requirements

## Quick Start

```bash
pip install lkb
```

### CLI

```bash
# Decompose a goal
lkb decompose "Build a user authentication system" --methods tdd-red-green

# Validate a task transition
lkb validate --task-id task-001 --change '{"kind": "transition_status", "payload": {"status": "completed"}}'

# Explain a task's reasoning chain
lkb explain task-001

# View audit log
lkb audit task-001 --since 2026-07-20T00:00:00Z
```

### Python API

```python
from lkb import TaskDecomposer, LogicalKanbanService, get_logical_kanban

# Decompose a goal
decomposer = TaskDecomposer()
plan = decomposer.decompose(
    goal="Build a CLI tool to monitor GitHub PRs",
    context={"tasks": {}, "workspace_root": "/path/to/repo"},
    method_refs=("exploratory-prototyping", "tdd-red-green"),
)
print(plan.to_json(indent=2))

# Validate a task transition
runtime = get_logical_kanban(None)
service = LogicalKanbanService(runtime)
result = service.validate(
    task_id="task-001",
    proposed_change={"kind": "transition_status", "payload": {"status": "completed"}},
)
print(result.to_dict())
```

### MCP Server

```bash
# Using the MCP CLI (requires mcp CLI installed)
mcp run lkb.mcp.server:server

# Or via stdio
python -m lkb.mcp.server
```

The MCP server exposes 4 tools:
- `decompose_task` — Decompose a goal into a validated task plan
- `validate_task` — Validate a proposed task state transition
- `explain` — Explain the reasoning chain for a task
- `audit` — Return the audit log for a task

## Architecture

```
lkb/
├── __init__.py              # Public API
├── types.py                 # Core datatypes (LkbChatMessage, LkbToolResult, LkbValidationContext)
├── flags.py                 # Feature flags with graceful fallback
├── runtime.py               # LogicalKanbanRuntime (duck-typed context access)
├── decomposer.py            # Task decomposition (F-149)
├── rule_engine.py           # Rule engine (R-001..R-006)
├── service.py               # Core service (propose/validate/commit)
├── solver_adapter.py        # Multi-solver adapter
├── solver_pipeline.py       # Solver orchestration
├── solver_atp.py            # ATP solver interface
├── causal.py                # Causal verification (F-141)
├── llm_fact_extractor.py    # LLM fact extraction (F-143)
├── ambiguity_detector.py    # Ambiguity detection
├── audit.py                 # Audit log
├── explain.py               # Reasoning chain explanation
├── adapters.py              # Tool adapters
├── method_library.py        # Method library (F-150)
├── method_seed.py           # Method seeding (F-151)
├── method_proposer.py       # Method proposal
├── method_governance.py     # Method governance
├── method_coverage.py       # Method coverage analysis
├── method_prompt.py         # Method prompts
├── acceptance_template.py   # Acceptance templates (F-155)
├── external_config.py       # External configuration (F-154)
├── ontology_graph.py        # Ontology graph
├── operation_schema.py      # Operation schema
├── scheduling_solver.py     # Scheduling solver (F-152)
├── truth_maintenance.py     # Truth maintenance system
├── commit_gate_fuzzy.py     # Fuzzy commit gating
├── fuzzy_patterns.py        # Fuzzy pattern library
├── fuzzy_types.py           # Fuzzy type definitions
├── multiworld_validator.py  # Multi-world validator
├── world_generator.py       # World generator
├── glossary.py              # Built-in glossary
├── ir.py                    # Internal representation
├── ir_hash.py               # IR hashing
├── ir_renderer.py           # IR rendering
├── predicate_extractor.py   # Predicate extraction
├── metrics.py               # Metrics
├── solver_limits.py         # Solver resource limits
└── atp/                     # ATP solver backends (F-142)
    ├── base.py
    ├── prover9.py
    ├── mace4.py
    ├── vampire.py
    └── ...
```

## Dependencies

**Core**: Zero external dependencies (stdlib only).

**Optional**:
- `z3-solver>=4.12` — Z3 ATP backend
- `prover9-py>=0.0.5` — Prover9 ATP backend
- `clingo>=5.6` — Clingo ASP backend

## License

MIT — see `LICENSE` for details.