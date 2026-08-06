"""Multi-agent tree builder.

P0 simplified version: builds a flat tree from AgentTreeNode objects.
P1 full version would infer hierarchy from mailbox cross-references.
"""

from __future__ import annotations

from typing import Any

from ..models.viz_models import AgentTreeNode, SessionVizData


class AgentTreeBuilder:
    """Build agent tree visualization data."""

    def build(self, session: SessionVizData) -> dict[str, Any]:
        """Build tree data for ECharts tree chart."""
        nodes = session.agent_tree
        if not nodes:
            return {"nodes": [], "edges": [], "root": None}

        # Build edges from parent_id references
        edges: list[dict[str, str]] = []
        node_map: dict[str, AgentTreeNode] = {}
        root_id: str | None = None

        for node in nodes:
            node_map[node.agent_id] = node
            if node.parent_id is None:
                root_id = node.agent_id
            else:
                edges.append({"source": node.parent_id, "target": node.agent_id})

        # If no explicit root, pick the first node
        if root_id is None and nodes:
            root_id = nodes[0].agent_id

        return {
            "nodes": [self._node_to_dict(n) for n in nodes],
            "edges": edges,
            "root": root_id,
        }

    def _node_to_dict(self, node: AgentTreeNode) -> dict[str, Any]:
        return {
            "id": node.agent_id,
            "name": node.name,
            "parentId": node.parent_id,
            "children": node.children,
            "depth": node.depth,
            "status": node.status.value,
            "stats": node.stats.model_dump(),
            "metadata": node.metadata,
        }
