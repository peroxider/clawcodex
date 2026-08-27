"""Ledger data model.

Revision / Head / Lineage / Edge are the row objects of the four ledger tables.
RevisionInput is the write-side input: it converges the crystallizer's merged candidate
+ scope + audit into an explicit structure, so callers do not assemble SQL parameters directly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Ledger operation types
OPS = frozenset(
    {
        "create",
        "absorb",
        "repair",
        "retract",
        "supersede",
        "split",
        "promote",
        "expire",
        "dispute",
        "verify",
    }
)

# Maturity states (phase three enables the state machine; phase one only writes candidate/active/superseded)
STATUSES = frozenset(
    {
        "candidate",
        "active",
        "canonical",
        "disputed",
        "superseded",
        "retracted",
        "expired",
    }
)

# Lineage relationship types
RELATIONS = frozenset({"absorbed_into", "superseded_by", "split_from"})

SCOPE_KEYS = ("user_id", "agent_id", "run_id")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_crystal_id() -> str:
    """Mint a stable lineage identity.

    Shaped as cr_<32 hex chars>, clearly distinguished from mem0's bare UUID for easy
    identification in logs and filenames. Python 3.12 has no uuid7, so uuid4 is used here --
    the ledger's ordering comes from the auto-incrementing rev_id, and crystal_id only needs
    to be unique, not sortable.
    """
    return f"cr_{uuid.uuid4().hex}"


def new_batch_id() -> str:
    """Mint a batch number for one background crystallization run, used for batch-level rollback."""
    return f"batch_{uuid.uuid4().hex[:16]}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(text: Any, default: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def build_scope(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Converge the three scope IDs into a dict; empty values are not written."""
    scope: dict[str, str] = {}
    for key, value in (("user_id", user_id), ("agent_id", agent_id), ("run_id", run_id)):
        if value:
            scope[key] = str(value)
    return scope


def scope_from_metadata(metadata: Any) -> dict[str, str]:
    """Extract scope from existing crystal metadata, so absorb reuses the original scope."""
    meta = metadata if isinstance(metadata, dict) else {}
    return build_scope(
        user_id=meta.get("user_id"),
        agent_id=meta.get("agent_id"),
        run_id=meta.get("run_id"),
    )


@dataclass
class RevisionInput:
    """Complete input for one ledger write.

    body / asset / facets come directly from the crystallizer's merged candidate (already passed
    through the retention judge and validate_candidate), and field names stay consistent with the
    existing crystal_metadata to reduce cognitive cost.
    """

    crystal_id: str
    batch_id: str
    op: str
    body: str
    asset: dict[str, Any] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    knowledge_type: str | None = None
    asset_type: str | None = None
    subject: str | None = None
    confidence: float | None = None
    source_ids: list[str] = field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    actor: str = "crystallizer"
    rationale: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, str] = field(default_factory=dict)
    # Cross-crystal relationship: (from_crystal_id, to_crystal_id, relation)
    lineage: list[tuple[str, str, str]] = field(default_factory=list)

    def validate(self) -> None:
        if not self.crystal_id:
            raise ValueError("RevisionInput.crystal_id 不能为空")
        if not self.batch_id:
            raise ValueError("RevisionInput.batch_id 不能为空")
        if self.op not in OPS:
            raise ValueError(f"未知的账本操作: {self.op}")
        if self.status not in STATUSES:
            raise ValueError(f"未知的成熟度状态: {self.status}")
        if not str(self.body or "").strip():
            raise ValueError("RevisionInput.body 不能为空")
        for _, _, relation in self.lineage:
            if relation not in RELATIONS:
                raise ValueError(f"未知的血缘关系: {relation}")


@dataclass(frozen=True)
class Revision:
    """A row of crystal_revision."""

    rev_id: int
    crystal_id: str
    parent_rev: int | None
    batch_id: str
    version: int
    op: str
    status: str
    body: str
    asset: dict[str, Any]
    facets: dict[str, Any]
    knowledge_type: str | None
    asset_type: str | None
    subject: str | None
    confidence: float | None
    source_ids: list[str]
    content_hash: str
    valid_from: str | None
    valid_to: str | None
    recorded_at: str
    actor: str | None
    rationale: str | None
    audit: dict[str, Any]
    scope: dict[str, str]

    @classmethod
    def from_row(cls, row: Any) -> "Revision":
        return cls(
            rev_id=int(row["rev_id"]),
            crystal_id=row["crystal_id"],
            parent_rev=row["parent_rev"],
            batch_id=row["batch_id"],
            version=int(row["version"]),
            op=row["op"],
            status=row["status"],
            body=row["body"],
            asset=_json_loads(row["asset_json"], {}),
            facets=_json_loads(row["facets_json"], {}),
            knowledge_type=row["knowledge_type"],
            asset_type=row["asset_type"],
            subject=row["subject"],
            confidence=row["confidence"],
            source_ids=_json_loads(row["source_ids_json"], []),
            content_hash=row["content_hash"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            recorded_at=row["recorded_at"],
            actor=row["actor"],
            rationale=row["rationale"],
            audit=_json_loads(row["audit_json"], {}),
            scope=_json_loads(row["scope_json"], {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Dict form for API / audit output."""
        return {
            "rev_id": self.rev_id,
            "crystal_id": self.crystal_id,
            "parent_rev": self.parent_rev,
            "batch_id": self.batch_id,
            "version": self.version,
            "op": self.op,
            "status": self.status,
            "body": self.body,
            "asset": self.asset,
            "facets": self.facets,
            "knowledge_type": self.knowledge_type,
            "asset_type": self.asset_type,
            "subject": self.subject,
            "confidence": self.confidence,
            "source_ids": self.source_ids,
            "source_count": len(self.source_ids),
            "content_hash": self.content_hash,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "recorded_at": self.recorded_at,
            "actor": self.actor,
            "rationale": self.rationale,
            "audit": self.audit,
            "scope": self.scope,
        }


@dataclass(frozen=True)
class Head:
    """A row of crystal_head -- the only mutable state in the ledger."""

    crystal_id: str
    rev_id: int
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "Head":
        return cls(
            crystal_id=row["crystal_id"],
            rev_id=int(row["rev_id"]),
            updated_at=row["updated_at"],
        )


@dataclass(frozen=True)
class Lineage:
    """A row of crystal_lineage."""

    rev_id: int
    from_crystal_id: str
    to_crystal_id: str
    relation: str

    @classmethod
    def from_row(cls, row: Any) -> "Lineage":
        return cls(
            rev_id=int(row["rev_id"]),
            from_crystal_id=row["from_crystal_id"],
            to_crystal_id=row["to_crystal_id"],
            relation=row["relation"],
        )


@dataclass(frozen=True)
class Edge:
    """A row of crystal_edge -- graph projection, deterministically derived from asset, zero-LLM."""

    edge_id: int
    rev_id: int
    crystal_id: str
    subject: str
    predicate: str
    object: str
    valid_from: str | None
    valid_to: str | None
    status: str

    @classmethod
    def from_row(cls, row: Any) -> "Edge":
        return cls(
            edge_id=int(row["edge_id"]),
            rev_id=int(row["rev_id"]),
            crystal_id=row["crystal_id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            status=row["status"],
        )


def derive_edges(asset: Any) -> list[tuple[str, str, str]]:
    """Deterministically derive (subject, predicate, object) triples from asset.

    Zero-LLM: only reads the structured fields already present in asset. Free-text relations
    cannot be reliably split into triples by "subject --relation--> object", so additional
    derivation only happens when a relations item is shaped like "a|b|c" or "a -> b";
    otherwise it is skipped (rather invent nothing than invent wrong).
    """
    source = asset if isinstance(asset, dict) else {}
    subject = str(source.get("subject") or "").strip()
    predicate = str(source.get("predicate") or "").strip()
    obj = str(source.get("object") or "").strip()

    edges: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def push(s: str, p: str, o: str) -> None:
        if not (s and p and o):
            return
        key = (s.lower(), p.lower(), o.lower())
        if key in seen:
            return
        seen.add(key)
        edges.append((s, p, o))

    push(subject, predicate, obj)

    relations = source.get("relations")
    if isinstance(relations, (list, tuple)):
        for item in relations:
            text = str(item).strip()
            if not text:
                continue
            for separator in ("|", "->", "→"):
                if separator in text:
                    parts = [part.strip() for part in text.split(separator)]
                    if len(parts) == 3:
                        push(parts[0], parts[1], parts[2])
                    elif len(parts) == 2 and subject:
                        push(subject, parts[0], parts[1])
                    break
    return edges


def crystal_metadata_from_revision(revision: Revision) -> dict[str, Any]:
    """Rebuild the ledger revision into the existing crystal_metadata shape.

    Field names stay consistent with the metadata that semantic_crystallizer writes to mem0,
    so that when phase two switches the read path, downstream (_apply_display_text / composition
    statistics) does not need changes.
    """
    metadata: dict[str, Any] = {
        "layer": "crystallized",
        "knowledge_type": revision.knowledge_type,
        "asset_type": revision.asset_type,
        "asset": revision.asset,
        "subject": revision.subject,
        "confidence": revision.confidence,
        "source_ids": revision.source_ids,
        "source_count": len(revision.source_ids),
        "evidence_source_ids": revision.source_ids,
        "version": revision.version,
        "status": revision.status,
        "crystallized_at": revision.recorded_at,
        "display_text": revision.body,
        "facets": revision.facets,
        "crystal_id": revision.crystal_id,
        "rev_id": revision.rev_id,
        "content_hash": revision.content_hash,
        "validity_disputed": revision.op == "dispute" or revision.status == "disputed",
    }
    metadata.update(revision.scope)
    return metadata


def json_field(value: Any) -> str:
    """JSON serialization entry point from dataclass to SQL parameter."""
    return _json_dumps(value)
