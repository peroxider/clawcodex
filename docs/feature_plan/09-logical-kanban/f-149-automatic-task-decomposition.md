# F-149 Automatic Task Decomposition

## Goal

Provide an agent-loop capability that turns a user’s high-level natural-language goal into a structured, logic-aware task plan. The decomposer acts as a **proposal generator**: it emits candidate tasks, dependency edges, acceptance criteria, and explicit assumptions, but it does not mutate `ToolContext.tasks` directly. Every generated task must still pass the existing Logical Kanban validation gate before it is committed.

## Scope

### In-Scope

- A new `TaskDecomposer` service in `clawcodex_ext/logical_kanban/` that:
  - Accepts a goal string plus optional context and acceptance criteria.
  - Uses an LLM to propose a list of concrete tasks with descriptions.
  - Annotates each proposed task with LKB metadata (`acceptance_proof`, `assertions`, `assumptions`, `strict_acceptance` when appropriate).
  - Produces a dependency graph (`blockedBy` / `blocks`) for the proposed tasks.
- A new `TaskDecompose` tool that exposes the service to the agent loop.
- Prompt-level guidance so agents know when and how to invoke `TaskDecompose`.
- Fuzzy/ambiguous acceptance criteria detection on the generated plan before it is shown to the agent.
- Validation of the proposed dependency graph using the existing `Layer1RuleEngine` / `SolverPipeline`.

### Out-of-Scope

- Automatic execution of the generated plan (tasks are still created via `TaskCreate`/`TaskUpdate` by the agent).
- Full Canonical Assertion IR generation in the first version; assertions may be stored as structured metadata strings until F-131 stabilizes.
- Persistent plan templates or learned decomposition patterns in the MVP.
- Orchestrator-specific dashboards or daemon-side planning state.

## Non-Goals

- Replace the agent’s planning ability; the tool is an opt-in helper for complex multi-step work.
- Commit tasks without LKB validation.
- Introduce external planning services or databases.

## Interfaces

### Service

```python
# clawcodex_ext/logical_kanban/decomposer.py

@dataclass
class DecompositionPlan:
    decomposition_run_id: str
    goal: str
    tasks: tuple[ProposedTask, ...]
    dependencies: tuple[tuple[str, str], ...]  # (prerequisite_id, dependent_id)
    assumptions: tuple[str, ...]
    ambiguity_report: AmbiguityReport | None
    validation_run_id: str | None

@dataclass
class ProposedTask:
    proposed_task_id: str  # temporary, replaced after TaskCreate
    subject: str
    description: str
    active_form: str
    acceptance_criteria: tuple[str, ...]
    blocked_by: tuple[str, ...]
    lkb_metadata: dict[str, Any]

class TaskDecomposer:
    def __init__(self, llm_provider: Any | None = None) -> None: ...

    def decompose(
        self,
        goal: str,
        *,
        context: str = "",
        acceptance_criteria: tuple[str, ...] = (),
        max_steps: int = 8,
        existing_tasks: tuple[dict[str, Any], ...] = (),
    ) -> DecompositionPlan: ...
```

### Tool

```python
# clawcodex_ext/tool_system/tools/task_decompose.py

TaskDecomposeTool = build_tool(
    name="TaskDecompose",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "minLength": 1},
            "context": {"type": "string"},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["goal"],
    },
    call=_task_decompose_call,
    prompt="...",
    description="Decompose a high-level goal into a validated task plan.",
    is_enabled=lambda: is_todo_v2_enabled() and is_logical_kanban_enabled(),
)
```

Tool output shape:

```json
{
  "decompositionRunId": "D-...",
  "goal": "...",
  "tasks": [
    {
      "proposedTaskId": "tmp-...",
      "subject": "...",
      "description": "...",
      "activeForm": "...",
      "acceptanceCriteria": ["..."],
      "blockedBy": ["tmp-..."],
      "lkbMetadata": { "assertions": [...], "acceptance_proof": "..." }
    }
  ],
  "dependencies": [["tmp-a", "tmp-b"]],
  "assumptions": ["..."],
  "ambiguities": [...],
  "validation": { "validationRunId": "V-...", "result": "pass|fail", "issues": [...] }
}
```

## Acceptance Criteria

- [ ] `TaskDecompose` is available to the agent only when both `is_todo_v2_enabled()` and `is_logical_kanban_enabled()` are true.
- [ ] The decomposer returns a deterministic JSON shape that an agent can convert into `TaskCreate`/`TaskUpdate` calls.
- [ ] The generated plan is validated by `LogicalKanbanService` before the tool returns; cycles, impossible dependencies, or ambiguous acceptance criteria are surfaced as `ValidationIssue`s.
- [ ] The tool does not mutate `ToolContext.tasks` or `ToolContext.todos`.
- [ ] Generated task subjects are in imperative form and each task has at least one acceptance criterion.
- [ ] An audit event `lkb_decomposition_proposed` is emitted for every decomposition run.
- [ ] Unit tests cover:
  - simple goal → multiple tasks,
  - dependency ordering,
  - rejection of cyclic generated plans,
  - detection of vague acceptance criteria,
  - feature-gate behavior.

## Dependencies

- F-126 LKB Agent Loop Foundation (tool context integration)
- F-129 Task V2 Integration (`TaskCreate`/`TaskUpdate` schemas)
- F-132 Layer-1 Rule Engine (dependency graph validation)
- F-134 Fuzzy Input and Multi-World Handling (acceptance-criteria ambiguity detection)
- F-136 Explainability and Repair Suggestions (surfacing validation issues to the agent)

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| LLM generates invalid or hallucinated dependencies | Run the plan through `Layer1RuleEngine`/`SolverPipeline` and surface issues before returning |
| Agent over-uses the tool for trivial tasks | Prompt guidance and tool prompt state it is for 3+ step goals; classifier can be tuned |
| Generated tasks bypass strict acceptance | Validate `acceptance_proof` metadata shape; reject plans with missing proofs when strict mode is on |
| Maintenance burden of prompt engineering | Keep prompt in a single module; add unit tests that assert on output schema, not exact wording |

## Implementation Notes

- Implement the service in `clawcodex_ext/logical_kanban/decomposer.py`.
  - Reuse the strict-JSON plan-generation pattern from `clawcodex_ext/services/ultraplan/llm_planner.py` (schema + retry loop + template).
  - Use `clawcodex_ext/services/ultraplan/models.py` dataclasses (`Plan`, `Step`, `AcceptanceCriteria`) as inspiration for the internal model, then convert to the `DecompositionPlan` / `ProposedTask` output shape.
  - The generated plan must be validated with `LogicalKanbanService.snapshot()` + `SolverPipeline` / `Layer1RuleEngine` before the tool returns.
- Add the tool in `clawcodex_ext/tool_system/tools/task_decompose.py` and register it in `clawcodex_ext/tool_system/tools/__init__.py` / `ALL_STATIC_TOOLS`.
  - The tool is **read-only with respect to task state**: it returns a validated plan, but the agent must still call `TaskCreate`/`TaskUpdate` to commit tasks. This preserves the existing LKB prove-before-commit invariant.
- Extend `task_v2_guidelines()` in `clawcodex_ext/agent/agent_definitions.py` to mention `TaskDecompose`.
  - Also update `extensions/orchestrator/prompt_builder.py:311-320` if orchestrator-launched agents need explicit “decompose first” guidance.
- Add tests in `tests/logical_kanban/test_f149_task_decomposition.py`.
- Consider auto-decompose heuristics in a later iteration (e.g. orchestrator `pipeline` / `coordinator` modes seeding tasks), but keep the MVP tool-driven to avoid silent automation surprises.
