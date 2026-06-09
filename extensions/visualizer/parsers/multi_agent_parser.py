"""Multi-agent cross-reference parser (F-91-B).

Infers agent hierarchy from session metadata and orchestrator control files.
P0 simplified version: produces a flat agent list with parent references.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import AgentTreeNode, BarStatus, OperationStats

logger = logging.getLogger(__name__)


class MultiAgentParser:
    """Parse multi-agent tree from orchestrator control files.

    P0 simplified: reads workspace/.orchestrator_control/runs/{run_id}/
    for agent metadata and produces a flat agent tree.
    """

    def __init__(self) -> None:
        pass

    def parse_workspace(self, workspace_path: Path | str, run_id: str) -> list[AgentTreeNode]:
        """Parse agent tree from workspace orchestrator control dir."""
        workspace_path = Path(workspace_path)
        control_dir = workspace_path / ".orchestrator_control" / "runs" / run_id
        if not control_dir.exists():
            return []

        nodes: list[AgentTreeNode] = []

        # Look for agent metadata files
        agent_meta_path = control_dir / "agent_meta.json"
        if agent_meta_path.exists():
            try:
                data = json.loads(agent_meta_path.read_text(encoding="utf-8"))
                agents = data.get("agents", [])
                for agent in agents:
                    node = self._agent_dict_to_node(agent, run_id)
                    if node:
                        nodes.append(node)
            except Exception as e:
                logger.debug("Failed to parse agent_meta.json for %s: %s", run_id, e)

        # Fallback: if no agent_meta.json, create a single root node
        if not nodes:
            nodes.append(
                AgentTreeNode(
                    agent_id=f"agent-{run_id[:8]}",
                    name="primary-agent",
                    session_ref=run_id,
                    status=BarStatus.SUCCESS,
                )
            )

        return nodes

    def _agent_dict_to_node(self, data: dict[str, Any], run_id: str) -> AgentTreeNode | None:
        agent_id = data.get("id") or data.get("agent_id", "")
        if not agent_id:
            return None
        return AgentTreeNode(
            agent_id=agent_id,
            name=data.get("name", agent_id),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
            session_ref=run_id,
            status=BarStatus(data.get("status", "success")),
            depth=data.get("depth", 0),
            metadata=data.get("metadata", {}),
        )
