"""Data models for composite tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompositeStage:
    """A single stage within a composite tool workflow."""

    name: str
    description: str
    agent_ref: str | None = None
    expected_duration_s: int = 30


@dataclass
class CompositeToolSpec:
    """Specification for a composite (macro) tool.

    A composite tool is registered as an ``AgentToolSpec`` (so the agent can
    invoke it) **and** can emit a ``workflow.yaml`` sidecar for the orchestrator.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    stages: list[CompositeStage] = field(default_factory=list)
    tags: tuple[str, ...] = field(default_factory=lambda: ("composite", "macro"))
    aliases: tuple[str, ...] = field(default_factory=tuple)
