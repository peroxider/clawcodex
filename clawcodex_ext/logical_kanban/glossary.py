"""Glossary registry for Canonical IR predicates.

A glossary defines the vocabulary that assertions may use.  Every predicate
appearing in a CanonicalAssertion must resolve to a glossary entry; unknown
predicates put the assertion into ``needs_glossary_review``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """A single predicate or type entry in the glossary."""

    name: str
    category: Literal['type', 'status', 'relation', 'permission', 'proof', 'operation', 'meta']
    arity: int | tuple[int, ...] | None = None
    description: str = ''
    aliases: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'category': self.category,
            **({'arity': self.arity} if self.arity is not None else {}),
            **({'description': self.description} if self.description else {}),
            **({'aliases': sorted(self.aliases)} if self.aliases else {}),
        }


@dataclass(frozen=True, slots=True)
class Glossary:
    """Immutable predicate glossary."""

    entries: dict[str, GlossaryEntry] = field(default_factory=dict)

    def add(self, entry: GlossaryEntry) -> 'Glossary':
        """Return a new glossary with ``entry`` added."""
        return Glossary({**self.entries, entry.name: entry})

    def union(self, other: 'Glossary') -> 'Glossary':
        """Return a new glossary merging both entry sets."""
        merged = dict(self.entries)
        merged.update(other.entries)
        return Glossary(merged)

    def resolve(self, name: str) -> GlossaryEntry | None:
        """Look up a predicate by canonical name."""
        return self.entries.get(name)

    def contains(self, name: str) -> bool:
        return name in self.entries

    def __contains__(self, name: str) -> bool:
        return self.contains(name)

    def predicate_names(self) -> frozenset[str]:
        return frozenset(self.entries)


def _e(
    name: str,
    category: Literal['type', 'status', 'relation', 'permission', 'proof', 'operation', 'meta'],
    arity: int | tuple[int, ...] | None = None,
    description: str = '',
    aliases: tuple[str, ...] | None = None,
) -> GlossaryEntry:
    return GlossaryEntry(
        name=name,
        category=category,
        arity=arity,
        description=description,
        aliases=frozenset(aliases or ()),
    )


BUILT_IN_GLOSSARY: Glossary = Glossary(
    {
        entry.name: entry
        for entry in (
            # Types
            _e('Task', 'type', 1, 'A work item tracked by the kanban system.'),
            _e('Status', 'type', 2, 'Associates a task with a status value.'),
            # Status values
            _e('Pending', 'status', 1, 'Task is waiting to be started.'),
            _e('Ready', 'status', 1, 'Task has no active blockers and may start.'),
            _e('Doing', 'status', 1, 'Task is currently in progress.'),
            _e('Done', 'status', 1, 'Task is completed.'),
            _e('Blocked', 'status', 1, 'Task has active blockers preventing progress.'),
            # Relations
            _e('Requires', 'relation', 2, 'Task A requires task B to be completed first.'),
            _e('Blocks', 'relation', 2, 'Task A blocks task B from proceeding.'),
            _e('CanMoveTo', 'relation', 2, 'Task is permitted to transition to a target status.'),
            _e('Permitted', 'permission', 2, 'General permission relation between entities.'),
            # Proof
            _e('HasAcceptanceProof', 'proof', 1, 'Task carries a completed acceptance proof.'),
            # Meta / logical operations
            _e('Contradicts', 'operation', 2, 'Two assertions or facts are mutually inconsistent.'),
            _e('Assumes', 'meta', 2, 'Assertion depends on an assumption that may be retracted.'),
            _e('DerivedFrom', 'meta', 2, 'Fact or assertion is derived from another.'),
            _e('Active', 'meta', 1, 'Entity is currently active in the working world.'),
            _e('Invalid', 'meta', 1, 'Entity or assertion has been invalidated.'),
        )
    }
)


__all__ = [
    'BUILT_IN_GLOSSARY',
    'Glossary',
    'GlossaryEntry',
]
