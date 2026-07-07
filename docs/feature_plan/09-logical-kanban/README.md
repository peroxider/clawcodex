# 09 Logical Kanban

This directory decomposes `docs/feature_plan/logical_kanban_v3_spec.md` into implementable feature requirements.

Important integration decision: LKB is an agent-loop todo/task enhancement layer, not an orchestrator-only subsystem. The primary integration points are `ToolContext.todos`, `ToolContext.tasks`, `TodoWrite`, `TaskCreate`, `TaskUpdate`, `TaskList`, and the task-list transcript UI. Orchestrator and workflows consume LKB indirectly by using the same todo/task tools.

## Remaining Feature Map

以下特性已在代码中完全实现，需求文档已删除：F-126 ~ F-144, F-148 ~ F-150。当前目录仅保留尚未实现的特性。

| ID | Requirement | Primary Area | Source Chapters | Status |
| --- | --- | --- | --- | --- |
| F-151 | Prompt-Integrated Method Reuse | inject method library summary into system prompt; guide LLM to reuse templates | 5, 10, 17 | ❌ 未实现 |
| F-152 | Bounded Scheduling Solver (OR-Tools CP-SAT) | closed scheduling sub-problem solving with resource constraints and time windows | 5, 10, 17 | ❌ 未实现 |
| F-153 | Method Library Growth & Governance | save-as-method workflow, version management, approval CLI, coverage metrics | 5, 10, 17 | ❌ 未实现 |
| F-154 | External Configuration Import | import domain ontology / operation schema / method library from external files | 5, 10, 17 | ❌ 未实现 |
| F-155 | Acceptance Template Registry | elevate `AcceptanceTemplate` to top-level concept; standalone registry with governance | 5, 10, 17 | ❌ 未实现 |

## Architectural Placement

```text
Agent loop
  -> Tool dispatch
    -> TodoWrite / TaskCreate / TaskUpdate / TaskList
      -> LKB adapter
        -> facts snapshot
        -> rule engine / solver
        -> validation run / proof trace
        -> commit or deny
      -> ToolContext.todos / ToolContext.tasks
  -> transcript task widget / TUI

Orchestrator / workflows / subagents
  -> use the same todo/task tools
  -> receive the same LKB semantics
```

## Implementation Principle

The original specification describes a full proof-carrying kanban system. In ClawCodex, the first-class product surface is the agent's todo/task tool loop. Therefore every requirement here is phrased so it can ship incrementally inside the tool system before introducing external services or full solver stacks.

