"""AgentDefinition Protocol — interface for SOP-convertible agent definitions.

Defines the contract that ``extensions/sop_converter/`` consumes for agent
shapes. The default implementation is the
``clawcodex_ext.agent.agent_definitions.AgentDefinition`` dataclass; this
Protocol lets the SOP converter core refer to agents without importing
``clawcodex_ext`` directly.

Mirrors the field subset that the SOP converter actually consumes (see
``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.3). Optional fields are marked
``| None`` and use ``...`` for forward references where the runtime type
is not stable across providers (e.g. ``get_system_prompt``).

The accompanying constant namespace ``_AgentToolConstants`` exposes the
small set of tool-name/toolset constants that ``bundle_context`` and
``agent_builder`` currently borrow from
``clawcodex_ext.agent.constants``:
  - ``MAX_INLINE_TOOL_DISPLAY``
  - ``POS_PROXY_BASE_TOOLS``
  - ``POS_SOP_DOMAIN_AGENT_TOOLS``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal, Optional, Protocol, runtime_checkable

__all__ = [
    "AgentDefinitionProtocol",
    "AgentSourceLiteral",
    "AgentToolConstants",
]


# Matches ``clawcodex_ext.agent.agent_definitions.AgentSource`` — kept as a
# Protocol-level Literal so consumers can pattern-match without importing
# the upstream enum/literal. Re-export kept verbatim to preserve IDE
# auto-completion parity.
AgentSourceLiteral = Literal[
    "built-in",
    "user",
    "project",
    "managed",
    "plugin",
    "dynamic",
    "clawcodex_ext",
    "extensions",
]


@runtime_checkable
class AgentDefinitionProtocol(Protocol):
    """Protocol for an agent definition that the SOP converter can serialize.

    Field names mirror ``AgentDefinition`` to keep ``@runtime_checkable``
    semantics intact. The few Plan-listed aliases (``name``,
    ``memory_scope``, ``persistent``) are exposed as read-only properties
    so consumers can refer to them without re-mapping to ``agent_type`` /
    ``memory`` / ``background``. Dataclass implementations that don't
    expose those aliases must adapt them via the
    ``extensions/sop_converter/adapters/agent_definition_adapter.py``
    default adapter (Phase 3+).
    """

    agent_type: str
    when_to_use: str
    tools: Optional[list[str]]
    source: AgentSourceLiteral
    base_dir: str
    model: Optional[str]
    provider: Optional[str]
    permission_mode: Optional[str]
    max_turns: Optional[int]
    background: bool
    color: Optional[str]
    memory: Optional[str]
    omit_claude_md: bool
    disallowed_tools: Optional[list[str]]
    hooks: Optional[dict[str, Any]]
    skills: Optional[list[str]]
    isolation: Optional[Literal["worktree", "remote"]]
    required_mcp_servers: Optional[list[str]]
    mcp_servers: Optional[list[Any]]
    effort: Optional[str]
    get_system_prompt: Optional[Callable[..., str]]
    callback: Optional[Callable[[], None]]
    critical_system_reminder: Optional[str]


class AgentToolConstants:
    """SOP tool-name and toolset constants (Layer-2 surface).

    Concrete values are pinned to the matching names in
    ``clawcodex_ext.agent.constants`` (2026-07-23 snapshot). Updating
    the upstream list requires updating both; the Protocol layer adds
    a single source of truth for downstream consumers.
    """

    MAX_INLINE_TOOL_DISPLAY: int = 20

    POS_PROXY_BASE_TOOLS: frozenset[str] = frozenset(
        (
            "Skill",
            "ToolSearch",
            "Agent",
            "Read",
            "TodoWrite",
            "StructuredOutput",
        )
    )

    POS_SOP_DOMAIN_AGENT_TOOLS: frozenset[str] = frozenset(
        (
            "Skill",
            "ToolSearch",
            "Bash",
            "TodoWrite",
            "StructuredOutput",
        )
    )
