"""Template data model.

A :class:`Template` is a reusable, named bundle of agent configuration
fields (tools, model, prompt fragments, max_turns, etc.) that can be
referenced from an agent definition via ``agent: template_name``. The
template itself is intentionally **not** an agent definition: the
resolver (see :mod:`resolver`) is responsible for merging a base
template with an inline override into a concrete agent config.

The schema is field-driven and permissive: anything serialisable as
JSON/YAML is a valid field value, but the template carries a strict
``id``, ``title``, optional ``description``, and an optional ``fields``
mapping that lists the field names the template declares. Validation
rejects empty ids, oversized ids, ids with whitespace or path-unsafe
characters, and any field name that is not a valid Python identifier.

This module is the single source of truth for what a template looks
like on disk; the registry and resolver layer only deal with
:class:`Template` instances, never raw dicts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Reuse the id pattern that ultraplan/models.py established for plan ids
# so cross-service lookups stay consistent.
_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_TITLE_MAX = 200
_DESCRIPTION_MAX = 2_000
_FIELDS_MAX = 64
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _validate_id(value: str, *, what: str = "id") -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} must be a non-empty string")
    if not _ID_RE.match(value):
        raise ValueError(
            f"{what} has invalid characters or length: {value!r} "
            "(expected [A-Za-z0-9._-]{1,64})"
        )


def _validate_title(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("title must be a non-empty string")
    if len(value) > _TITLE_MAX:
        raise ValueError(
            f"title exceeds {_TITLE_MAX} characters (got {len(value)})"
        )


def _validate_description(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("description must be a string when provided")
    if len(value) > _DESCRIPTION_MAX:
        raise ValueError(
            f"description exceeds {_DESCRIPTION_MAX} characters "
            f"(got {len(value)})"
        )


def _validate_fields(value: Mapping[str, Any] | None) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("fields must be a mapping when provided")
    if len(value) > _FIELDS_MAX:
        raise ValueError(
            f"fields exceeds {_FIELDS_MAX} entries (got {len(value)})"
        )
    for name in value:
        if not isinstance(name, str) or not _FIELD_NAME_RE.match(name):
            raise ValueError(
                f"field name must match {_FIELD_NAME_RE.pattern!r}: "
                f"got {name!r}"
            )


def _validate_metadata(value: Mapping[str, Any] | None) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be a mapping when provided")
    for key in value:
        if not isinstance(key, str) or not key:
            raise ValueError(f"metadata keys must be non-empty strings: {key!r}")


@dataclass(frozen=True)
class Template:
    """A reusable agent configuration template.

    Attributes:
        id: Stable identifier referenced by ``agent: <id>`` in agent
            definitions. Id-pattern enforced (see :data:`_ID_RE`).
        title: Short human-readable name (max 200 chars).
        description: Optional long-form description (max 2_000 chars).
        fields: Optional mapping of field name -> default value. Used
            both to declare what the template contributes and to give
            a baseline value when no inline override is supplied. Field
            names must be valid Python identifiers.
        metadata: Optional free-form metadata (e.g. tags, version).
            Keys must be non-empty strings; values are arbitrary JSON-
            compatible scalars.
        source: Provenance label — ``built-in``, ``user``, ``project``,
            ``managed``, or ``plugin``. Mirrors ``AgentSource`` in
            :mod:`src.agent.agent_definitions` but kept as a plain
            string here so this module has no upstream dependency.
    """

    id: str
    title: str
    description: str | None = None
    fields: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source: str = "user"

    def __post_init__(self) -> None:
        _validate_id(self.id)
        _validate_title(self.title)
        _validate_description(self.description)
        _validate_fields(self.fields)
        _validate_metadata(self.metadata)
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "source": self.source,
        }
        if self.description is not None:
            out["description"] = self.description
        if self.fields:
            out["fields"] = dict(self.fields)
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Template":
        if not isinstance(data, dict):
            raise ValueError("template payload must be a JSON object")
        # Required fields. Missing -> fail loudly (corrupt payload).
        if "id" not in data:
            raise ValueError("template payload missing required key: id")
        if "title" not in data:
            raise ValueError("template payload missing required key: title")
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description"),
            fields=data.get("fields") or {},
            metadata=data.get("metadata") or {},
            source=data.get("source", "user"),
        )


__all__ = [
    "Template",
]