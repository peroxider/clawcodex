"""Team-only tool visibility filter.

When ``ToolContext.team`` is not an active team (i.e. the session has
no team context), drop tools that can only do useful work inside a
team: ``SendMessage`` (inter-agent messaging / broadcast), and the
team-management tools ``TeamCreate`` / ``TeamDelete``. The model's
self-introduction in single-user REPL sessions used to mis-call
``SendMessage { to: "*" }`` as a way of "replying"; hiding the tool
from the API schemas removes that path entirely.

This module is pure (no I/O, no globals, no upstream-tool mutation)
so it can be unit-tested in isolation and reused anywhere upstream
or downstream assembles a tool list.
"""

from __future__ import annotations

from typing import Iterable, TypeVar

# Mirrors the "team-only" subset of
# ``src.coordinator.mode.INTERNAL_WORKER_TOOLS``. We intentionally do
# not import that constant: coordinator mode is a separate axis (env
# var), and we want this filter to be usable in any context.
TEAM_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "SendMessage",
        "TeamCreate",
        "TeamDelete",
    }
)


_T = TypeVar("_T")


def has_team_context(team: object) -> bool:
    """Return True iff a team context is active.

    A team context is active when ``team`` is a non-empty dict
    (the shape set by ``src.tool_system.tools.team.TeamCreate`` at
    ``context.team = team_dict``). Anything else — ``None``, empty
    dict, malformed value — is treated as "no team".
    """
    return isinstance(team, dict) and bool(team)


def filter_team_only_tools(
    tools: Iterable[_T],
    has_team: bool,
    *,
    name_attr: str = "name",
) -> list[_T]:
    """Return ``tools`` minus any team-only entries when no team is active.

    Args:
        tools: An iterable of tool-like objects. Each must expose a
            ``name`` attribute (or whatever ``name_attr`` points to).
        has_team: Result of :func:`has_team_context` on the relevant
            ``ToolContext.team``. ``True`` short-circuits — all tools
            pass through.
        name_attr: Attribute name used to read the tool's display
            name. Defaults to ``"name"`` to match the ``Tool`` dataclass.

    Returns:
        A list copy of ``tools`` with team-only entries removed when
        ``has_team`` is False; the original elements (same order) when
        ``has_team`` is True.
    """
    if has_team:
        return list(tools)
    return [t for t in tools if getattr(t, name_attr, None) not in TEAM_ONLY_TOOL_NAMES]


__all__ = [
    "TEAM_ONLY_TOOL_NAMES",
    "has_team_context",
    "filter_team_only_tools",
]
