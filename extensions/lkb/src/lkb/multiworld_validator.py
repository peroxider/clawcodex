"""Per-world validation for multi-world assertions.

Each generated world is validated independently against the Layer1 rule engine.
The result is a list of WorldValidationResult records that capture the result,
derived facts, proof trace, and a stable conclusion hash for aggregation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .fuzzy_types import ValidationResultForWorld, WorldValidationResult
from .ir_hash import canonical_hash

if TYPE_CHECKING:
    from .fuzzy_types import World
    from .rule_engine import Layer1RuleEngine
    from .types import FactsSnapshot

def _result_to_world_result(result: str) -> ValidationResultForWorld:
    if result == "pass":
        return "pass"
    if result == "fail":
        return "fail"
    if result == "unknown":
        return "unknown"
    if result == "timeout":
        return "timeout"
    return "unknown"

def _snapshot_with_world_facts(
    snapshot: "FactsSnapshot",
    world: "World",
) -> "FactsSnapshot":
    """Return a snapshot that includes the world's assumption facts."""
    extra_facts: list[str] = []
    for assumption in world.assumptions:
        extra_facts.append(
            f"Assumes({assumption.assertion_id}, {assumption.assumption_id}, {assumption.assumed_value})"
        )
    return replace(snapshot, facts=snapshot.facts + tuple(extra_facts))

class MultiWorldValidator:
    """Validate a set of worlds independently using the Layer1 engine."""

    def __init__(self, engine: "Layer1RuleEngine") -> None:
        self.engine = engine

    def validate(
        self,
        worlds: list["World"],
        snapshot: "FactsSnapshot",
        *,
        target_task_id: str | None = None,
        target_status: str | None = None,
    ) -> list[WorldValidationResult]:
        """Return a validation result for every world.

        When ``target_task_id`` and ``target_status`` are supplied, the engine
        answers the transition query in the context of each world.  Otherwise
        the engine simply derives all facts for the snapshot.
        """
        results: list[WorldValidationResult] = []
        for world in worlds:
            world_snapshot = _snapshot_with_world_facts(snapshot, world)
            engine_result = self.engine.evaluate(
                world_snapshot,
                target_task_id=target_task_id,
                target_status=target_status,
            )
            conclusion_hash = canonical_hash(
                {
                    "derivedFacts": list(engine_result.derived_facts),
                    "result": engine_result.result,
                }
            )
            results.append(
                WorldValidationResult(
                    world_id=world.world_id,
                    result=_result_to_world_result(engine_result.result),
                    conclusion_hash=conclusion_hash,
                    derived_facts=engine_result.derived_facts,
                    proof_trace=engine_result.proof_trace,
                )
            )
        return results

__all__ = ["MultiWorldValidator"]
