# F-138 Solver Layer Roadmap

## Goal

Define how LKB evolves from in-process rules to external symbolic solvers without blocking MVP delivery.

## Layers

### Layer 1: Python Rule Engine

- Dependency propagation.
- Blocked/ready inference.
- Cycle detection.
- Acceptance proof checks.

### Layer 2: Datalog-Compatible Engine

- Compile facts and rules to a Datalog-like representation.
- Use for larger dependency graphs and traceable derivations.

### Layer 3: ASP / clingo

- Multi-world enumeration.
- Alternative plan generation.
- Conflict-set exploration.

### Layer 4: SMT / Z3

- Invariant checks.
- Confidence propagation constraints.
- Counterexample generation.

### Layer 5: ATP / TPTP

- Optional advanced proof-carrying assertions.
- Not part of local MVP.

## Requirements

- Solver adapters share one `ValidationRun` result shape.
- External solvers are optional dependencies.
- Timeouts and unknown results deny strict commits.
- Layer 1 remains available as fallback.

## Acceptance Criteria

- The service can run with no external solver installed.
- Adding a solver adapter does not change Task V2 tool schemas.
- Solver errors are surfaced as validation results, not uncaught tool crashes.

