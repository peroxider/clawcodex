"""F-89: unified ``@agent-name`` mention parsing for all entry points.

This module is the single source of truth for resolving ``@agent-<type>``
and ``@"<type> (agent)"`` mentions. CLI, REPL, TUI, headless, and the
orchestrator all funnel their raw input through :func:`parse_mentions`
so the four entry points agree on:

* the regex (case-insensitive, kebab / snake / camel accepted)
* the dedupe semantics (first occurrence wins)
* the unknown-agent behaviour (silent drop + optional strict mode)

Implementation notes
--------------------
* The regexes mirror :data:`clawcodex_ext.command_system.input_processing._AGENT_MENTION_*_RE`
  and are intentionally kept in sync. The canonical home now lives
  here; the older module re-exports the helpers for backwards compat.
* ``expand_mentions`` produces the ``agent_mention`` attachment dicts
  that downstream ``processAgentMentions`` (TypeScript) consumes. Both
  shapes (``unquoted`` and ``quoted``) collapse to the same attachment
  shape so the LLM sees one consistent interface.
* Strict mode (``raise_on_unknown=True``) is opt-in and currently used
  by the orchestrator's pre-flight validator; the user-facing entry
  points stay silent-on-unknown to match historical UX.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# Canonical regex for the unquoted form. Accepts ``@agent-<type>`` where
# the type is one or more word / digit / ``:`` / ``.`` / ``@`` / ``-``
# characters. Must be preceded by start-of-string or whitespace so a
# literal ``user@example.com`` is never matched. Case-insensitive on the
# ``agent-`` literal so ``@Agent-Foo`` parses the same as ``@agent-foo``.
_UNQUOTED_RE = re.compile(
    r"(?:^|(?<=\s))@(agent-[\w:.@\-]+)",
    re.UNICODE | re.IGNORECASE,
)

# Canonical regex for the quoted form: ``@"<type> (agent)"``.
_QUOTED_RE = re.compile(
    r'(?:^|(?<=\s))@"([\w:.@\-]+) \(agent\)"',
    re.UNICODE | re.IGNORECASE,
)


@dataclass(frozen=True)
class AgentMention:
    """One parsed mention. ``kind`` distinguishes the surface syntax
    (``unquoted`` / ``quoted``) so callers can preserve user intent."""

    agent_type: str
    kind: str  # "unquoted" | "quoted"
    span: tuple[int, int]


def _normalise_type(raw: str) -> str:
    """Lower-case + strip the optional ``agent-`` prefix.

    The canonical registry stores agent types without the ``agent-``
    prefix; the unquoted form carries it as part of the literal token.
    The quoted form already has the prefix stripped by the regex, but
    we re-apply here so both paths land on the same key.
    """
    raw = raw.strip().lower()
    if raw.startswith("agent-"):
        raw = raw[len("agent-") :]
    return raw


def parse_mentions(
    text: str,
    *,
    known_types: Iterable[str] | None = None,
    raise_on_unknown: bool = False,
) -> list[AgentMention]:
    """Extract every ``@agent-name`` mention from ``text``.

    Args:
        text: Raw user input (may contain multiple mentions).
        known_types: Optional allow-list of agent-type strings. When
            provided, mentions whose type is not in the set are dropped
            (or raised, see ``raise_on_unknown``).
        raise_on_unknown: When True, an unknown mention raises
            ``UnknownAgentMentionError``. When False (default), unknown
            mentions are silently dropped so stray ``@agent-foo``
            doesn't pollute the prompt context — same UX as the
            TypeScript implementation.

    Returns:
        Ordered list of parsed mentions, deduped by ``agent_type``.
        First occurrence wins; subsequent duplicates are filtered.
    """
    if not text:
        return []

    known_set: set[str] | None = (
        {t.strip().lower() for t in known_types if t} if known_types is not None else None
    )

    out: list[AgentMention] = []
    seen: set[str] = set()

    def _record(agent_type: str, kind: str, span: tuple[int, int]) -> None:
        normalised = _normalise_type(agent_type)
        if not normalised or normalised in seen:
            return
        if known_set is not None and normalised not in known_set:
            if raise_on_unknown:
                raise UnknownAgentMentionError(normalised)
            return
        seen.add(normalised)
        out.append(AgentMention(agent_type=normalised, kind=kind, span=span))

    for match in _UNQUOTED_RE.finditer(text):
        _record(match.group(1), "unquoted", match.span(0))
    for match in _QUOTED_RE.finditer(text):
        _record(match.group(1), "quoted", match.span(0))

    return out


def expand_mentions(
    text: str,
    agents: Iterable[Any] | None,
    *,
    raise_on_unknown: bool = False,
) -> list[dict[str, str]]:
    """Find mentions and resolve them against a live agent registry.

    Mirrors ``expand_agent_mentions`` in
    :mod:`clawcodex_ext.command_system.input_processing` so existing
    callers stay compatible. Each resolved mention produces one
    ``agent_mention`` attachment dict consumed by the LLM context.
    """
    if not text or agents is None:
        return []

    known_types: list[str] = []
    for agent in agents:
        agent_type = getattr(agent, "agent_type", None)
        if agent_type is None and isinstance(agent, dict):
            agent_type = agent.get("agent_type")
        if isinstance(agent_type, str) and agent_type:
            known_types.append(agent_type)
    if not known_types:
        return []

    mentions = parse_mentions(
        text,
        known_types=known_types,
        raise_on_unknown=raise_on_unknown,
    )
    return [{"kind": "agent_mention", "agent_type": m.agent_type} for m in mentions]


def is_agent_mention(text: str) -> bool:
    """Cheap predicate: does ``text`` contain any ``@agent-...`` mention?

    Use this for routing decisions (e.g. TUI's fast-path when the user
    has typed just a mention) without paying for the full parse cost.
    """
    return bool(_UNQUOTED_RE.search(text) or _QUOTED_RE.search(text))


def extract_agent_type(token: str) -> str | None:
    """If ``token`` looks like ``@agent-<type>`` or ``@"<type> (agent)"``,
    return the normalised ``<type>``; otherwise None.

    Useful for entry points that receive one token at a time (CLI argv,
    slash-command parser) and need to decide whether to dispatch to an
    agent or treat the input as a regular prompt.
    """
    if not token:
        return None
    # Try unquoted first.
    m = _UNQUOTED_RE.fullmatch(token.strip())
    if m is not None:
        return _normalise_type(m.group(1))
    # Try quoted (strip surrounding quotes first).
    cleaned = token.strip()
    if cleaned.startswith('@"') and cleaned.endswith('"'):
        inner = cleaned[2:-1]
        m = _QUOTED_RE.fullmatch(f'@"{inner}"')
        if m is not None:
            return _normalise_type(m.group(1))
    return None


class UnknownAgentMentionError(ValueError):
    """Raised by :func:`parse_mentions` when ``raise_on_unknown=True`` and
    a mention resolves to an agent type that is not in ``known_types``.
    """

    def __init__(self, agent_type: str) -> None:
        super().__init__(f"unknown agent mention: @agent-{agent_type}")
        self.agent_type = agent_type


__all__ = [
    "AgentMention",
    "UnknownAgentMentionError",
    "extract_agent_type",
    "expand_mentions",
    "is_agent_mention",
    "parse_mentions",
]