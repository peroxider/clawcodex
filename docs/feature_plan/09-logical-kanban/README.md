# 09 Logical Kanban

This directory decomposes `docs/feature_plan/logical_kanban_v3_spec.md` into implementable feature requirements.

Important integration decision: LKB is an agent-loop todo/task enhancement layer, not an orchestrator-only subsystem. The primary integration points are `ToolContext.todos`, `ToolContext.tasks`, `TodoWrite`, `TaskCreate`, `TaskUpdate`, `TaskList`, and the task-list transcript UI. Orchestrator and workflows consume LKB indirectly by using the same todo/task tools.

## Feature Map

| ID | Requirement | Primary Area | Source Chapters |
| --- | --- | --- | --- |
| F-126 | Agent Loop Foundation | tool context, session lifecycle | 1-4, 11 |
| F-127 | Task Context Adapter | `ToolContext.todos/tasks` normalization | 5, 13 |
| F-128 | Propose/Validate/Commit Tool Contract | todo/task write contract | 3, 11, 14 |
| F-129 | Task V2 Integration | `TaskCreate/List/Get/Update/Output` | 5, 10, 17 |
| F-130 | TodoWrite Compatibility | legacy TodoWrite bridge | 5, 11 |
| F-131 | Canonical IR and Glossary | assertion IR, predicate registry | 6-8, 26 |
| F-132 | Layer-1 Rule Engine | dependency and state inference | 5, 6, 10 |
| F-133 | Validation Runs and Proof Trace | validation records, reproducibility | 5, 14, 15 |
| F-134 | Fuzzy Input and Multi-World Handling | ambiguity detection, possible worlds | 8, 9, 24 |
| F-135 | Assumptions and Truth Maintenance | hypothesis invalidation | 9, 12, 24 |
| F-136 | Explainability and Repair Suggestions | model-facing and UI explanations | 15, 16 |
| F-137 | Persistence and Audit Events | local/session storage, event log | 13, 18, 20 |
| F-138 | Solver Layer Roadmap | Datalog, ASP, SMT, ATP adapters | 10, 21, 22 |
| F-139 | Security, Performance, Observability | NFRs and operations | 18-20, 25 |
| F-140 | Orchestrator Adoption Through Todo Tools | orchestrator as consumer | 17, 22-23 |
| F-141 | Causal Verification Layer (CAP-compatible) | synthetic causal graph, causal_weight gate | 10.6, 22.3 |
| F-142 | External ATP (Vampire / Prover9 / Mace4) | optional TPTP subprocess adapters, async proof enrichment | 10.5, 22.4 |
| F-143 | Runtime LLM Knowledge Facts | LLM as fact source at L1 (pre-processor) / L2 (solver adapter) / L3 (ambiguity fallback); deterministic kernel preserved | 22.4 |
| F-144 | Legacy Todo Path Fuzzy-Gate Coverage (P0) | every `TodoWrite` replacement is gated by `commit_gate_fuzzy_check` on per-todo content | — |
| F-145 | Disambiguating Tokens as Confidence Boosters (P0) | known-disambiguating tokens become first-class `DisambiguatingToken` entries; the matcher-exclusion anti-pattern is replaced | 9.4 |
| F-146 | Question-Context Suppression for Interpretation Refinement (P1) | every keyword-driven boost in `_refine_interpretations` and `_apply_disambiguating_tokens` checks the surrounding question frame | 9.4 |
| F-147 | Movement-Phrase Matcher Tolerance (P1) | `missing_subject` matcher allows 0–8 intervening characters; widens verb class; adds `出发去`/`前往`/`去到`/`head to`/`going to` | 9.4 |
| F-148 | Remove Car-Wash Demo Scenario from Default Library (P1) | default `FuzzyPatternLibrary` carries only generic patterns (verbs 做 / 完成 / nouns 距离 / 质量); scenario-bound patterns are supplied by downstream callers via `library.add(...)`; parent feature for the F-143 walkthrough update + F-145/F-146/F-147 doc rewording | 9.4 |

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

