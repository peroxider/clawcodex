"""Bridge dispatch table builder for wrapper/hybrid stage execution.

This module materializes the stage-level execution plan produced by the
capability mapper.  It is intentionally lightweight: the heavy lifting
(library detection, agent wiring, health checks) lives in the mapper and
health-check modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..capability.models import ExecutionMode, StageAgentMap
from ..extractors.models import WorkflowGraph


def build_bridge_tables(
    graph: WorkflowGraph,
    agent_map: StageAgentMap,
    source_dir: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]]] | None:
    """Build dispatch and output tables for wrapper/hybrid stages.

    Returns ``None`` when no stage needs a generated bridge (i.e. every
    stage is marked as ``AGENT_NATIVE``).  Otherwise returns:

    * ``stage_dispatch`` — maps stage id to runtime metadata such as the
      target agent, entry function, and working directory.
    * ``stage_outputs`` — maps stage id to the list of expected output
      artifacts declared by stage contracts.
    """
    stage_dispatch: dict[int, dict[str, Any]] = {}
    stage_outputs: dict[int, list[str]] = {}

    for stage in graph.stages:
        profile = agent_map.profile_for_stage(stage.id)
        if profile is None:
            continue
        if profile.execution_mode == ExecutionMode.AGENT_NATIVE:
            continue

        agent = profile.mapped_agent or agent_map.agent_for_stage(stage.id)
        if not agent:
            continue

        stage_dispatch[stage.id] = {
            "stage_id": stage.id,
            "stage_name": stage.name,
            "agent": agent,
            "entry_function": profile.entry_function,
            "source_dir": str(source_dir),
            "execution_mode": profile.execution_mode.value,
        }

        outputs: list[str] = []
        contract = graph.contracts.get(stage.id) if graph.contracts else None
        if contract is not None:
            outputs.extend(getattr(contract, "output_files", []) or [])
        stage_outputs[stage.id] = outputs

    if not stage_dispatch:
        return None
    return stage_dispatch, stage_outputs
