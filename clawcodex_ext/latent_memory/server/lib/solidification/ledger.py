"""Ledger core -- the single source of truth for the solidification layer.

Invariants (guaranteed by append_revision, verified by test_ledger.py):
  1. crystal_revision is INSERT-only. This module contains no UPDATE / DELETE against it.
  2. crystal_head is the only mutable state, and can be fully rebuilt by replaying the ledger
     with rebuild_heads().
  3. One write = one transaction = one fsync. revision / lineage / edge / head all land in the
     same BEGIN IMMEDIATE; partial failure is physically impossible.
  4. Idempotency: when content_hash equals the current head, no new revision is produced, so
     crystallization runs can be retried safely.
  5. Zero LLM calls.

A rollback only moves the crystal_head pointer; it modifies and deletes no historical data.
"""

from __future__ import annotations

import logging
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from clawcodex_ext.latent_memory.server.lib.solidification import schema
from clawcodex_ext.latent_memory.server.lib.solidification.hashing import content_hash
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    Edge,
    Head,
    Lineage,
    Revision,
    RevisionInput,
    SCOPE_KEYS,
    derive_edges,
    json_field,
    new_batch_id,
    utc_now,
)
from clawcodex_ext.latent_memory.server.lib.validity.models import (
    CaseInput,
    VerificationCase,
    VerificationEvidence,
    graph_adjudication_fingerprint,
    new_case_id,
    sha256_json,
)

logger = logging.getLogger("memory-server.solidification")

_FORCED_EVENT_OPS = frozenset({"retract", "supersede", "dispute", "verify"})

_REVISION_FIELDS = (
    "rev_id",
    "crystal_id",
    "parent_rev",
    "batch_id",
    "version",
    "op",
    "status",
    "body",
    "asset_json",
    "facets_json",
    "knowledge_type",
    "asset_type",
    "subject",
    "confidence",
    "source_ids_json",
    "content_hash",
    "valid_from",
    "valid_to",
    "recorded_at",
    "actor",
    "rationale",
    "audit_json",
    "scope_json",
)

_REVISION_COLUMNS = ", ".join(_REVISION_FIELDS)
# When JOINing crystal_head, rev_id / crystal_id exist in both tables, so the table alias must be explicit
_REVISION_COLUMNS_R = ", ".join(f"r.{field}" for field in _REVISION_FIELDS)

_CASE_FIELDS = (
    "case_id",
    "case_key",
    "case_type",
    "state",
    "priority",
    "scope_json",
    "subject",
    "predicate",
    "left_crystal_id",
    "left_head_rev",
    "right_crystal_id",
    "right_head_rev",
    "trigger_rev_id",
    "trigger_payload_json",
    "policy_version",
    "evidence_round",
    "decision_input_hash",
    "attempts",
    "next_attempt_at",
    "lease_owner",
    "lease_until",
    "opened_rev_ids_json",
    "result_rev_ids_json",
    "result_json",
    "last_error",
    "created_at",
    "updated_at",
)
_CASE_COLUMNS = ", ".join(_CASE_FIELDS)


class LedgerError(Exception):
    """A ledger write or read failed."""


class AppendResult:
    """Return value of append_revision.

    skipped=True means content_hash equals the current head, so no new revision was produced --
    the caller skips embedding recomputation and git commit accordingly.
    """

    __slots__ = ("revision", "skipped", "reason")

    def __init__(self, revision: Revision | None, *, skipped: bool, reason: str = "") -> None:
        self.revision = revision
        self.skipped = skipped
        self.reason = reason

    @property
    def rev_id(self) -> int | None:
        return self.revision.rev_id if self.revision else None

    @property
    def crystal_id(self) -> str | None:
        return self.revision.crystal_id if self.revision else None

    def __repr__(self) -> str:
        return (
            f"AppendResult(rev_id={self.rev_id}, crystal_id={self.crystal_id}, "
            f"skipped={self.skipped}, reason={self.reason!r})"
        )


class CrystalLedger:
    """Append-only event ledger.

    Single-writer assumption (design doc 7.5): the crystallizer writes on a single background
    thread. This class serializes writes with an in-process write lock, and SQLite WAL guarantees
    reads never block writes. If concurrent multi-process crystallization is added later, a
    single-writer queue must be layered on top, rather than relying on SQLite's lock retry.
    """

    def __init__(self, db_path: str, *, timeout: float = 30.0):
        self._db_path = db_path
        self._timeout = timeout
        self._write_lock = threading.Lock()
        self._local = threading.local()
        with self._connect() as conn:
            schema.migrate(conn, now=utc_now())

    @property
    def db_path(self) -> str:
        return self._db_path

    # ── Connection and transactions ──────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return the current thread's connection. sqlite3 connections are not shareable across
        threads, so they are cached per thread."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = schema.connect(self._db_path, timeout=self._timeout)
            self._local.conn = conn
        return conn

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        yield self._conn()

    @contextmanager
    def _write_txn(self) -> Iterator[sqlite3.Connection]:
        """One write transaction. BEGIN IMMEDIATE takes the write lock immediately, avoiding
        upgrade deadlocks under WAL."""
        with self._write_lock:
            conn = self._conn()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── Writes ───────────────────────────────────────────────────────────

    def append_revision(self, entry: RevisionInput) -> AppendResult:
        """Append a revision and move the head. The whole operation completes in one transaction.

        Idempotency: skip only when the observable state is exactly identical to the current head
        and op is not an explicit state transition. content_hash only answers "does the vector
        need recomputation" and does not represent full state; changes to source_ids/confidence/
        scope must still append a revision to preserve full provenance.
        """
        return self.append_revisions([entry])[0]

    def append_revisions(self, entries: list[RevisionInput]) -> list[AppendResult]:
        """Atomically append a set of related revisions and move all heads."""
        if not entries:
            return []
        for entry in entries:
            entry.validate()
        with self._write_txn() as conn:
            return [self._append_revision_in_txn(conn, entry) for entry in entries]

    def _append_revision_in_txn(
        self, conn: sqlite3.Connection, entry: RevisionInput
    ) -> AppendResult:
        digest = content_hash(entry.body, entry.asset, entry.facets)
        now = utc_now()
        forced_event_op = entry.op in _FORCED_EVENT_OPS
        head_row = conn.execute(
            f"SELECT {_REVISION_COLUMNS_R}"
            " FROM crystal_head h JOIN crystal_revision r ON r.rev_id = h.rev_id"
            " WHERE h.crystal_id = ?",
            (entry.crystal_id,),
        ).fetchone()

        if head_row is not None:
            parent_rev = int(head_row["rev_id"])
            version = int(head_row["version"]) + 1
            current = Revision.from_row(head_row)
            unchanged = (
                current.content_hash == digest
                and current.status == entry.status
                and current.knowledge_type == entry.knowledge_type
                and current.asset_type == entry.asset_type
                and current.subject == entry.subject
                and current.confidence == entry.confidence
                and current.source_ids == list(entry.source_ids)
                and current.valid_from == (entry.valid_from or None)
                and current.valid_to == (entry.valid_to or None)
                and current.scope == entry.scope
            )
            if unchanged and not forced_event_op:
                return AppendResult(
                    current,
                    skipped=True,
                    reason="content_hash_unchanged",
                )
        else:
            parent_rev = None
            version = 1

        cursor = conn.execute(
            "INSERT INTO crystal_revision ("
            " crystal_id, parent_rev, batch_id, version, op, status,"
            " body, asset_json, facets_json, knowledge_type, asset_type, subject,"
            " confidence, source_ids_json, content_hash,"
            " valid_from, valid_to, recorded_at, actor, rationale, audit_json, scope_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry.crystal_id,
                parent_rev,
                entry.batch_id,
                version,
                entry.op,
                entry.status,
                entry.body,
                json_field(entry.asset),
                json_field(entry.facets),
                entry.knowledge_type,
                entry.asset_type,
                entry.subject,
                entry.confidence,
                json_field(list(entry.source_ids)),
                digest,
                entry.valid_from or None,
                entry.valid_to or None,
                now,
                entry.actor,
                entry.rationale,
                json_field(entry.audit),
                json_field(entry.scope),
            ),
        )
        rev_id = int(cursor.lastrowid)

        for from_id, to_id, relation in entry.lineage:
            conn.execute(
                "INSERT INTO crystal_lineage(rev_id, from_crystal_id, to_crystal_id, relation)"
                " VALUES (?,?,?,?)",
                (rev_id, from_id, to_id, relation),
            )

        for subject, predicate, obj in derive_edges(entry.asset):
            conn.execute(
                "INSERT INTO crystal_edge("
                " rev_id, crystal_id, subject, predicate, object, valid_from, valid_to, status"
                ") VALUES (?,?,?,?,?,?,?,?)",
                (
                    rev_id,
                    entry.crystal_id,
                    subject,
                    predicate,
                    obj,
                    entry.valid_from or None,
                    entry.valid_to or None,
                    entry.status,
                ),
            )

        conn.execute(
            "INSERT INTO crystal_head(crystal_id, rev_id, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(crystal_id) DO UPDATE SET rev_id=excluded.rev_id,"
            " updated_at=excluded.updated_at",
            (entry.crystal_id, rev_id, now),
        )
        conn.execute(
            "DELETE FROM crystal_head_detachment WHERE crystal_id = ?",
            (entry.crystal_id,),
        )
        revision = self._revision_by_id(conn, rev_id)
        if revision is None:
            raise LedgerError("append_revision: 修订写入后回读失败")
        return AppendResult(revision, skipped=False)

    def mark_status(
        self,
        crystal_id: str,
        *,
        status: str,
        op: str,
        batch_id: str,
        actor: str = "crystallizer",
        rationale: str | None = None,
        lineage: list[tuple[str, str, str]] | None = None,
        audit: dict[str, Any] | None = None,
    ) -> AppendResult:
        """Append a status-transition revision to an existing crystal; body carries over the current head.

        Absorbed old crystals go through this path: marked superseded + lineage written, not deleted.

        After a batch rollback detaches the pointer, the head is empty but history remains. In that
        case the tip revision's body is used: retracting an already-detached crystal must leave a
        trace, otherwise a delete request would be silently lost.
        """
        head = self.head(crystal_id) or self.tip_revision(crystal_id)
        if head is None:
            raise LedgerError(f"mark_status: crystal {crystal_id} 不在账本中")
        entry = RevisionInput(
            crystal_id=crystal_id,
            batch_id=batch_id,
            op=op,
            status=status,
            body=head.body,
            asset=head.asset,
            facets=head.facets,
            knowledge_type=head.knowledge_type,
            asset_type=head.asset_type,
            subject=head.subject,
            confidence=head.confidence,
            source_ids=list(head.source_ids),
            valid_from=head.valid_from,
            valid_to=head.valid_to,
            actor=actor,
            rationale=rationale,
            audit=audit or {},
            scope=dict(head.scope),
            lineage=list(lineage or []),
        )
        return self.append_revision(entry)

    # ── Reads ────────────────────────────────────────────────────────────

    def _revision_by_id(self, conn: sqlite3.Connection, rev_id: int) -> Revision | None:
        row = conn.execute(
            f"SELECT {_REVISION_COLUMNS} FROM crystal_revision WHERE rev_id = ?", (rev_id,)
        ).fetchone()
        return Revision.from_row(row) if row else None

    def revision(self, rev_id: int) -> Revision | None:
        """Read a single revision by rev_id."""
        return self._revision_by_id(self._conn(), int(rev_id))

    def head(self, crystal_id: str) -> Revision | None:
        """Read the revision currently pointed to by this crystal's pointer."""
        row = (
            self._conn()
            .execute(
                f"SELECT {_REVISION_COLUMNS_R} FROM crystal_revision r"
                " JOIN crystal_head h ON h.rev_id = r.rev_id WHERE h.crystal_id = ?",
                (crystal_id,),
            )
            .fetchone()
        )
        return Revision.from_row(row) if row else None

    def head_pointer(self, crystal_id: str) -> Head | None:
        row = (
            self._conn()
            .execute(
                "SELECT crystal_id, rev_id, updated_at FROM crystal_head WHERE crystal_id = ?",
                (crystal_id,),
            )
            .fetchone()
        )
        return Head.from_row(row) if row else None

    def history(self, crystal_id: str, *, ascending: bool = True) -> list[Revision]:
        """Read this crystal's full revision chain. History is immutable, so this is the whole truth."""
        order = "ASC" if ascending else "DESC"
        rows = (
            self._conn()
            .execute(
                f"SELECT {_REVISION_COLUMNS} FROM crystal_revision"
                f" WHERE crystal_id = ? ORDER BY rev_id {order}",
                (crystal_id,),
            )
            .fetchall()
        )
        return [Revision.from_row(row) for row in rows]

    def revision_chain(self, crystal_id: str, *, head_rev_id: int | None = None) -> list[Revision]:
        """Return only the current branch, ordered from genesis to the selected head.

        After a pointer rollback a crystal may fork, so ``history()`` is not a valid source for
        maturity counts. Tracing ``parent_rev`` makes derived state exactly replayable and
        automatically rollback-aware.
        """
        selected = self.revision(head_rev_id) if head_rev_id is not None else self.head(crystal_id)
        if selected is None or selected.crystal_id != crystal_id:
            return []
        revisions = {revision.rev_id: revision for revision in self.history(crystal_id)}
        chain: list[Revision] = []
        cursor: Revision | None = selected
        seen: set[int] = set()
        while cursor is not None:
            if cursor.rev_id in seen:
                raise LedgerError(f"revision parent cycle detected at rev {cursor.rev_id}")
            seen.add(cursor.rev_id)
            chain.append(cursor)
            cursor = revisions.get(cursor.parent_rev) if cursor.parent_rev is not None else None
        chain.reverse()
        return chain

    def crystal_exists(self, crystal_id: str) -> bool:
        """Whether this crystal identity has ever recorded any revision.

        ``head()`` is not a valid existence test: a batch rollback detaches the pointer while the
        immutable history remains. Callers that must classify an identifier (crystal vs raw memory)
        need this method, otherwise a detached crystal ID would be silently treated as a raw source ID.
        """
        if not crystal_id:
            return False
        row = (
            self._conn()
            .execute(
                "SELECT 1 FROM crystal_revision WHERE crystal_id = ? LIMIT 1",
                (crystal_id,),
            )
            .fetchone()
        )
        return row is not None

    def tip_revision(self, crystal_id: str) -> Revision | None:
        """Return the most recently recorded revision, ignoring the head pointer."""
        row = (
            self._conn()
            .execute(
                f"SELECT {_REVISION_COLUMNS} FROM crystal_revision WHERE crystal_id = ?"
                " ORDER BY rev_id DESC LIMIT 1",
                (crystal_id,),
            )
            .fetchone()
        )
        return Revision.from_row(row) if row else None

    def heads(
        self,
        *,
        user_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[Revision]:
        """List all current head revisions, filterable by scope and status."""
        sql = (
            f"SELECT {_REVISION_COLUMNS_R} FROM crystal_revision r"
            " JOIN crystal_head h ON h.rev_id = r.rev_id"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if statuses:
            clauses.append(f"r.status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.rev_id DESC"
        if limit is not None and user_id is None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn().execute(sql, params).fetchall()
        revisions = [Revision.from_row(row) for row in rows]
        if user_id is not None:
            # scope lives in a JSON column; filtering in Python is simpler than adding a generated
            # column index for JSON at this scale (thousands of rows), and avoids schema changes.
            revisions = [rev for rev in revisions if rev.scope.get("user_id") == user_id]
            if limit is not None:
                revisions = revisions[: int(limit)]
        return revisions

    def heads_referencing_source(
        self,
        source_id: str,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[Revision]:
        """Return the current heads referencing a raw memory ID.

        Compared to retrieval, deletion is rare, so scanning the compact head set avoids schema/index
        migrations for the JSON source list. Historical revisions are deliberately excluded: only the
        currently asserted knowledge needs to be retracted.
        """
        if not source_id:
            return []
        return [
            revision
            for revision in self.heads(statuses=statuses)
            if source_id in revision.source_ids
        ]

    def heads_matching_scope(self, scope: dict[str, str]) -> list[Revision]:
        """Return the current heads whose scope contains all requested key/value pairs."""
        filters = {key: str(value) for key, value in scope.items() if value}
        if not filters:
            return []
        return [
            revision
            for revision in self.heads()
            if all(revision.scope.get(key) == value for key, value in filters.items())
        ]

    def lineage_for_crystal(self, crystal_id: str) -> list[Lineage]:
        rows = (
            self._conn()
            .execute(
                "SELECT rev_id, from_crystal_id, to_crystal_id, relation FROM crystal_lineage"
                " WHERE from_crystal_id = ? OR to_crystal_id = ? ORDER BY rev_id",
                (crystal_id, crystal_id),
            )
            .fetchall()
        )
        return [Lineage.from_row(row) for row in rows]

    def edges_for_revision(self, rev_id: int) -> list[Edge]:
        rows = (
            self._conn()
            .execute(
                "SELECT edge_id, rev_id, crystal_id, subject, predicate, object,"
                " valid_from, valid_to, status FROM crystal_edge WHERE rev_id = ?"
                " ORDER BY edge_id",
                (int(rev_id),),
            )
            .fetchall()
        )
        return [Edge.from_row(row) for row in rows]

    def _live_graph_edges(self, *, user_id: str | None = None) -> list[Edge]:
        """Read only the edges belonging to current active/canonical heads.

        Filtering solely on ``crystal_edge.status`` is not enough, because once a crystal is
        superseded or rolled back, its historical active rows remain immutable. Joining
        ``crystal_head`` on the exact rev_id is the projection boundary.
        """
        rows = (
            self._conn()
            .execute(
                "SELECT e.edge_id, e.rev_id, e.crystal_id, e.subject, e.predicate,"
                " e.object, e.valid_from, e.valid_to, e.status, r.scope_json"
                " FROM crystal_edge e"
                " JOIN crystal_head h ON h.rev_id = e.rev_id"
                " JOIN crystal_revision r ON r.rev_id = e.rev_id"
                " WHERE r.status IN ('active','canonical')"
                " ORDER BY e.edge_id"
            )
            .fetchall()
        )
        result: list[Edge] = []
        for row in rows:
            if user_id is not None:
                try:
                    scope = json.loads(row["scope_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    scope = {}
                if scope.get("user_id") != user_id:
                    continue
            result.append(Edge.from_row(row))
        return result

    @staticmethod
    def _edge_dict(edge: Edge, *, depth: int | None = None) -> dict[str, Any]:
        # edge_id is the physical row key of a rebuildable projection. It changes after
        # rebuild_edges(), so exposing it would fabricate a stable ID.
        result: dict[str, Any] = {
            "rev_id": edge.rev_id,
            "crystal_id": edge.crystal_id,
            "subject": edge.subject,
            "predicate": edge.predicate,
            "object": edge.object,
            "valid_from": edge.valid_from,
            "valid_to": edge.valid_to,
            "status": edge.status,
        }
        if depth is not None:
            result["depth"] = depth
        return result

    def graph_traverse(
        self,
        subject: str,
        *,
        max_depth: int = 2,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Do a breadth-first outgoing traversal on the current head graph."""
        root = str(subject or "").strip()
        if not root:
            raise ValueError("graph subject cannot be empty")
        depth_limit = int(max_depth)
        if not 1 <= depth_limit <= 5:
            raise ValueError("graph max_depth must be between 1 and 5")
        edges = self._live_graph_edges(user_id=user_id)
        by_subject: dict[str, list[Edge]] = {}
        for edge in edges:
            by_subject.setdefault(edge.subject.casefold(), []).append(edge)

        frontier = {root.casefold()}
        visited_nodes = set(frontier)
        emitted: set[int] = set()
        results: list[dict[str, Any]] = []
        for depth in range(1, depth_limit + 1):
            next_frontier: set[str] = set()
            for node in sorted(frontier):
                for edge in by_subject.get(node, []):
                    if edge.edge_id not in emitted:
                        emitted.add(edge.edge_id)
                        results.append(self._edge_dict(edge, depth=depth))
                    target = edge.object.casefold()
                    if target not in visited_nodes:
                        visited_nodes.add(target)
                        next_frontier.add(target)
            if not next_frontier:
                break
            frontier = next_frontier
        return results

    @staticmethod
    def _parse_graph_time(value: str | None) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _edge_intervals_overlap(cls, left: Edge, right: Edge) -> bool:
        left_start = cls._parse_graph_time(left.valid_from)
        left_end = cls._parse_graph_time(left.valid_to)
        right_start = cls._parse_graph_time(right.valid_from)
        right_end = cls._parse_graph_time(right.valid_to)
        return not (
            left_end is not None
            and right_start is not None
            and left_end < right_start
            or right_end is not None
            and left_start is not None
            and right_end < left_start
        )

    def graph_conflicts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find deterministic temporal contradiction candidates without using an LLM."""
        subject_key = str(subject or "").strip().casefold()
        predicate_key = str(predicate or "").strip().casefold()
        groups: dict[tuple[str, str, str], list[Edge]] = {}
        for head in self.heads(statuses=("active", "canonical")):
            if user_id is not None and head.scope.get("user_id") != user_id:
                continue
            for edge in self.edges_for_revision(head.rev_id):
                key = (
                    json_field(head.scope),
                    edge.subject.casefold(),
                    edge.predicate.casefold(),
                )
                if subject_key and key[1] != subject_key:
                    continue
                if predicate_key and key[2] != predicate_key:
                    continue
                groups.setdefault(key, []).append(edge)

        results: list[dict[str, Any]] = []
        for edges in groups.values():
            for index, left in enumerate(edges):
                for right in edges[index + 1 :]:
                    if left.crystal_id == right.crystal_id:
                        continue
                    if left.object.casefold() == right.object.casefold():
                        continue
                    if not self._edge_intervals_overlap(left, right):
                        continue
                    results.append(
                        {
                            "subject": left.subject,
                            "predicate": left.predicate,
                            "left": self._edge_dict(left),
                            "right": self._edge_dict(right),
                            "reason": "different_objects_with_overlapping_validity",
                        }
                    )
        return results

    def candidate_graph_conflicts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find contradictions involving candidates, without exposing them to the active graph."""
        subject_key = str(subject or "").strip().casefold()
        predicate_key = str(predicate or "").strip().casefold()
        groups: dict[tuple[str, str, str], list[tuple[Edge, Revision]]] = {}
        for head in self.heads(statuses=("candidate", "active", "canonical")):
            # Candidates keep their status when disputed. Backfill their cases by excluding the
            # current forced dispute event until the case is resolved.
            if head.op == "dispute":
                continue
            if user_id is not None and head.scope.get("user_id") != user_id:
                continue
            scope_key = json_field(head.scope)
            for edge in self.edges_for_revision(head.rev_id):
                key = (scope_key, edge.subject.casefold(), edge.predicate.casefold())
                if subject_key and key[1] != subject_key:
                    continue
                if predicate_key and key[2] != predicate_key:
                    continue
                groups.setdefault(key, []).append((edge, head))

        results: list[dict[str, Any]] = []
        for values in groups.values():
            for index, (left, left_head) in enumerate(values):
                for right, right_head in values[index + 1 :]:
                    if left.crystal_id == right.crystal_id:
                        continue
                    if "candidate" not in (left_head.status, right_head.status):
                        continue
                    if left.object.casefold() == right.object.casefold():
                        continue
                    if not self._edge_intervals_overlap(left, right):
                        continue
                    results.append(
                        {
                            "subject": left.subject,
                            "predicate": left.predicate,
                            "left": self._edge_dict(left),
                            "right": self._edge_dict(right),
                            "reason": "different_objects_with_overlapping_validity",
                        }
                    )
        return results

    def rebuild_edges(self) -> dict[str, int]:
        """Rebuild the deterministic edge projection from the immutable revisions."""
        with self._write_txn() as conn:
            conn.execute("DELETE FROM crystal_edge")
            rows = conn.execute(
                f"SELECT {_REVISION_COLUMNS} FROM crystal_revision ORDER BY rev_id"
            ).fetchall()
            edge_count = 0
            through = 0
            for row in rows:
                revision = Revision.from_row(row)
                through = revision.rev_id
                for subject, predicate, obj in derive_edges(revision.asset):
                    conn.execute(
                        "INSERT INTO crystal_edge("
                        " rev_id, crystal_id, subject, predicate, object,"
                        " valid_from, valid_to, status) VALUES (?,?,?,?,?,?,?,?)",
                        (
                            revision.rev_id,
                            revision.crystal_id,
                            subject,
                            predicate,
                            obj,
                            revision.valid_from,
                            revision.valid_to,
                            revision.status,
                        ),
                    )
                    edge_count += 1
            conn.execute(
                "INSERT INTO projection_state(projection, through_rev, updated_at)"
                " VALUES ('graph',?,?) ON CONFLICT(projection) DO UPDATE SET"
                " through_rev=excluded.through_rev, updated_at=excluded.updated_at",
                (through, utc_now()),
            )
        return {"through_rev": through, "edges": edge_count}

    def max_rev_id(self) -> int:
        row = (
            self._conn()
            .execute("SELECT COALESCE(MAX(rev_id), 0) AS m FROM crystal_revision")
            .fetchone()
        )
        return int(row["m"])

    def batch_revisions(self, batch_id: str) -> list[Revision]:
        rows = (
            self._conn()
            .execute(
                f"SELECT {_REVISION_COLUMNS} FROM crystal_revision WHERE batch_id = ?"
                " ORDER BY rev_id",
                (batch_id,),
            )
            .fetchall()
        )
        return [Revision.from_row(row) for row in rows]

    def revisions_after(self, rev_id: int, *, limit: int = 100) -> list[Revision]:
        """Return the next batch of global revisions needed for incremental projections."""
        rows = (
            self._conn()
            .execute(
                f"SELECT {_REVISION_COLUMNS} FROM crystal_revision WHERE rev_id > ?"
                " ORDER BY rev_id LIMIT ?",
                (int(rev_id), max(1, int(limit))),
            )
            .fetchall()
        )
        return [Revision.from_row(row) for row in rows]

    # ── Validity verification workflow ──────────────────────────────────

    @staticmethod
    def _case_by_id_in_txn(conn: sqlite3.Connection, case_id: str) -> VerificationCase | None:
        row = conn.execute(
            f"SELECT {_CASE_COLUMNS} FROM verification_case WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        return VerificationCase.from_row(row) if row else None

    def verification_case(self, case_id: str) -> VerificationCase | None:
        return self._case_by_id_in_txn(self._conn(), case_id)

    def verification_cases(
        self,
        *,
        state: str | None = None,
        user_id: str | None = None,
        scope: dict[str, str] | None = None,
        limit: int = 100,
    ) -> list[VerificationCase]:
        requested_limit = max(1, min(int(limit), 1000))
        filters = {str(key): str(value) for key, value in (scope or {}).items() if value}
        if user_id is not None:
            filters["user_id"] = user_id
        sql = f"SELECT {_CASE_COLUMNS} FROM verification_case"
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("state = ?")
            params.append(state)
        for key in SCOPE_KEYS:
            if key in filters:
                clauses.append(f"json_extract(scope_json, '$.{key}') = ?")
                params.append(filters[key])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        params.append(requested_limit)
        cases = [
            VerificationCase.from_row(row) for row in self._conn().execute(sql, params).fetchall()
        ]
        return cases

    def resolved_graph_coexist_case_keys(self, policy_version: str) -> set[str]:
        """Return the semantic case identities accepted as coexisting under this policy.

        Keys are rebuilt from the resulting revisions, not the opening heads. This covers
        coexist decisions that simultaneously fix validity fields, while later pure status
        revisions still match without depending on rev_id.
        """
        rows = (
            self._conn()
            .execute(
                f"SELECT {_CASE_COLUMNS} FROM verification_case"
                " WHERE case_type='graph_conflict' AND state='resolved'"
                " AND policy_version=?"
                " AND json_extract(result_json, '$.decision')='coexist'",
                (str(policy_version),),
            )
            .fetchall()
        )
        keys: set[str] = set()
        conn = self._conn()
        for row in rows:
            case = VerificationCase.from_row(row)
            revisions = [
                revision
                for rev_id in case.result_rev_ids
                if (revision := self._revision_by_id(conn, rev_id)) is not None
            ]
            if len(revisions) < 2:
                continue
            keys.add(
                CaseInput(
                    case_type=case.case_type,
                    scope=case.scope,
                    subject=case.subject,
                    predicate=case.predicate,
                    left_crystal_id=case.left_crystal_id,
                    right_crystal_id=case.right_crystal_id,
                    policy_version=case.policy_version,
                    adjudication_fingerprint=graph_adjudication_fingerprint(*revisions),
                ).case_key
            )
        return keys

    @staticmethod
    def _dispute_entry(
        head: Revision, *, case_id: str, case_type: str, batch_id: str
    ) -> RevisionInput:
        status = "candidate" if head.status == "candidate" else "disputed"
        return RevisionInput(
            crystal_id=head.crystal_id,
            batch_id=batch_id,
            op="dispute",
            status=status,
            body=head.body,
            asset=dict(head.asset),
            facets=dict(head.facets),
            knowledge_type=head.knowledge_type,
            asset_type=head.asset_type,
            subject=head.subject,
            confidence=head.confidence,
            source_ids=list(head.source_ids),
            valid_from=head.valid_from,
            valid_to=head.valid_to,
            actor="validity_verifier",
            rationale=f"verification case opened: {case_type}",
            audit={
                "maturity": {"contradiction_delta": 1},
                "verification": {
                    "case_id": case_id,
                    "case_type": case_type,
                    "direction": "open",
                    "previous_status": head.status,
                },
            },
            scope=dict(head.scope),
        )

    def open_verification_case(
        self, case_input: CaseInput, *, dispute: bool = True
    ) -> tuple[VerificationCase, bool, list[AppendResult]]:
        """Atomically create the case and its dispute events; duplicates are read-only."""
        case_input.validate()
        case_id = new_case_id()
        now = utc_now()
        with self._write_txn() as conn:
            cursor = conn.execute(
                "INSERT INTO verification_case("
                " case_id, case_key, case_type, state, priority, scope_json,"
                " subject, predicate, left_crystal_id, left_head_rev,"
                " right_crystal_id, right_head_rev, trigger_rev_id,"
                " trigger_payload_json, policy_version, created_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(case_key) DO NOTHING",
                (
                    case_id,
                    case_input.case_key,
                    case_input.case_type,
                    case_input.initial_state,
                    max(0, min(int(case_input.priority), 100)),
                    json_field(case_input.scope),
                    case_input.subject,
                    case_input.predicate,
                    case_input.left_crystal_id,
                    case_input.left_head_rev,
                    case_input.right_crystal_id,
                    case_input.right_head_rev,
                    case_input.trigger_rev_id,
                    json_field(case_input.trigger_payload),
                    case_input.policy_version,
                    now,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    f"SELECT {_CASE_COLUMNS} FROM verification_case WHERE case_key = ?",
                    (case_input.case_key,),
                ).fetchone()
                if row is None:
                    raise LedgerError("verification case conflict could not be read")
                return VerificationCase.from_row(row), False, []

            results: list[AppendResult] = []
            if dispute:
                expected = {
                    case_input.left_crystal_id: case_input.left_head_rev,
                    case_input.right_crystal_id: case_input.right_head_rev,
                }
                batch_id = new_batch_id()
                for crystal_id, rev_id in expected.items():
                    if not crystal_id or rev_id is None:
                        continue
                    row = conn.execute(
                        f"SELECT {_REVISION_COLUMNS_R} FROM crystal_revision r"
                        " JOIN crystal_head h ON h.rev_id = r.rev_id"
                        " WHERE h.crystal_id = ?",
                        (crystal_id,),
                    ).fetchone()
                    if row is None or int(row["rev_id"]) != int(rev_id):
                        raise LedgerError(
                            f"verification input head changed: {crystal_id} expected {rev_id}"
                        )
                    head = Revision.from_row(row)
                    if head.status in ("superseded", "retracted", "expired"):
                        continue
                    results.append(
                        self._append_revision_in_txn(
                            conn,
                            self._dispute_entry(
                                head,
                                case_id=case_id,
                                case_type=case_input.case_type,
                                batch_id=batch_id,
                            ),
                        )
                    )
                conn.execute(
                    "UPDATE verification_case SET opened_rev_ids_json = ?, updated_at = ?"
                    " WHERE case_id = ?",
                    (json_field([result.rev_id for result in results]), now, case_id),
                )
            created = self._case_by_id_in_txn(conn, case_id)
            if created is None:
                raise LedgerError("verification case insert could not be read")
            return created, True, results

    def record_verification_evidence(
        self,
        case_id: str,
        evidence: list[dict[str, Any]],
        *,
        prompt_version: str,
        model_id: str,
        make_pending: bool = False,
    ) -> tuple[int, str]:
        """Append an immutable round of evidence and update its non-unique input hash."""
        with self._write_txn() as conn:
            case = self._case_by_id_in_txn(conn, case_id)
            if case is None:
                raise LedgerError(f"verification case not found: {case_id}")
            if case.state in ("resolved", "stale"):
                raise LedgerError(f"cannot add evidence to {case.state} case")
            round_id = case.evidence_round + 1
            now = utc_now()
            hashes: list[str] = []
            for item in evidence:
                observed_hash = str(item.get("observed_hash") or "")
                if not observed_hash:
                    raise ValueError("verification evidence requires observed_hash")
                hashes.append(observed_hash)
                conn.execute(
                    "INSERT OR IGNORE INTO verification_evidence("
                    " case_id, collection_round, source_kind, source_ref,"
                    " observed_hash, snapshot_json, recorded_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        case_id,
                        round_id,
                        str(item.get("source_kind") or "raw"),
                        str(item.get("source_ref") or ""),
                        observed_hash,
                        json_field(item.get("snapshot") or {}),
                        now,
                    ),
                )
            decision_hash = sha256_json(
                {
                    "case_key": case.case_key,
                    "evidence_hashes": sorted(hashes),
                    "prompt_version": prompt_version,
                    "model_id": model_id,
                }
            )
            state = "pending" if make_pending else case.state
            conn.execute(
                "UPDATE verification_case SET evidence_round = ?,"
                " decision_input_hash = ?, state = ?, updated_at = ? WHERE case_id = ?",
                (round_id, decision_hash, state, now, case_id),
            )
            return round_id, decision_hash

    def verification_evidence(
        self, case_id: str, *, collection_round: int | None = None
    ) -> list[VerificationEvidence]:
        if collection_round is None:
            case = self.verification_case(case_id)
            collection_round = case.evidence_round if case else 0
        rows = (
            self._conn()
            .execute(
                "SELECT evidence_id, case_id, collection_round, source_kind, source_ref,"
                " observed_hash, snapshot_json, recorded_at FROM verification_evidence"
                " WHERE case_id = ? AND collection_round = ? ORDER BY evidence_id",
                (case_id, int(collection_round)),
            )
            .fetchall()
        )
        return [VerificationEvidence.from_row(row) for row in rows]

    def claim_verification_cases(
        self,
        *,
        owner: str,
        limit: int,
        lease_seconds: float,
        max_attempts: int,
    ) -> list[VerificationCase]:
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        lease_until = (now + timedelta(seconds=max(1.0, lease_seconds))).isoformat()
        with self._write_txn() as conn:
            conn.execute(
                "UPDATE verification_case SET state='pending', lease_owner=NULL,"
                " lease_until=NULL, updated_at=? WHERE state='running' AND lease_until < ?",
                (now_text, now_text),
            )
            rows = conn.execute(
                f"SELECT {_CASE_COLUMNS} FROM verification_case"
                " WHERE state='pending' AND attempts < ?"
                " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
                " ORDER BY priority DESC, created_at LIMIT ?",
                (max(1, int(max_attempts)), now_text, max(1, int(limit))),
            ).fetchall()
            ids = [row["case_id"] for row in rows]
            for case_id in ids:
                conn.execute(
                    "UPDATE verification_case SET state='running', lease_owner=?,"
                    " lease_until=?, attempts=attempts+1, updated_at=? WHERE case_id=?",
                    (owner, lease_until, now_text, case_id),
                )
            claimed: list[VerificationCase] = []
            for case_id in ids:
                case = self._case_by_id_in_txn(conn, case_id)
                if case is not None:
                    claimed.append(case)
            return claimed

    def set_verification_case_state(
        self,
        case_id: str,
        state: str,
        *,
        error: str | None = None,
        next_attempt_at: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> VerificationCase:
        with self._write_txn() as conn:
            conn.execute(
                "UPDATE verification_case SET state=?, last_error=?, next_attempt_at=?,"
                " lease_owner=NULL, lease_until=NULL, result_json=COALESCE(?, result_json),"
                " updated_at=? WHERE case_id=?",
                (
                    state,
                    error,
                    next_attempt_at,
                    json_field(result) if result is not None else None,
                    utc_now(),
                    case_id,
                ),
            )
            case = self._case_by_id_in_txn(conn, case_id)
            if case is None:
                raise LedgerError(f"verification case not found: {case_id}")
            return case

    def retry_verification_case(self, case_id: str) -> VerificationCase:
        case = self.verification_case(case_id)
        if case is None:
            raise LedgerError(f"verification case not found: {case_id}")
        if case.state == "resolved":
            return case
        if case.state in ("stale", "waiting_evidence"):
            raise LedgerError(f"cannot retry a {case.state} verification case")
        with self._write_txn() as conn:
            conn.execute(
                "UPDATE verification_case SET state='pending', attempts=0,"
                " next_attempt_at=NULL, lease_owner=NULL, lease_until=NULL,"
                " last_error=NULL, updated_at=? WHERE case_id=?",
                (utc_now(), case_id),
            )
            refreshed = self._case_by_id_in_txn(conn, case_id)
            if refreshed is None:
                raise LedgerError(f"verification case not found: {case_id}")
            return refreshed

    def append_verification_decision(
        self,
        case_id: str,
        expected_heads: dict[str, int],
        revision_inputs: list[RevisionInput],
        *,
        decision: dict[str, Any],
    ) -> tuple[str, list[AppendResult]]:
        """Atomically apply a verified decision under optimistic head validation."""
        for entry in revision_inputs:
            entry.validate()
        with self._write_txn() as conn:
            case = self._case_by_id_in_txn(conn, case_id)
            if case is None:
                raise LedgerError(f"verification case not found: {case_id}")
            if case.state == "resolved":
                if case.result and case.result != decision:
                    raise LedgerError("verification case already resolved with another decision")
                return "resolved", [
                    AppendResult(
                        self._revision_by_id(conn, rev_id), skipped=True, reason="case_resolved"
                    )
                    for rev_id in case.result_rev_ids
                ]
            for crystal_id, expected_rev in expected_heads.items():
                row = conn.execute(
                    "SELECT rev_id FROM crystal_head WHERE crystal_id = ?", (crystal_id,)
                ).fetchone()
                if row is None or int(row["rev_id"]) != int(expected_rev):
                    conn.execute(
                        "UPDATE verification_case SET state='stale', lease_owner=NULL,"
                        " lease_until=NULL, last_error='head_changed', updated_at=?"
                        " WHERE case_id=?",
                        (utc_now(), case_id),
                    )
                    return "stale", []
            results = [self._append_revision_in_txn(conn, entry) for entry in revision_inputs]
            result_rev_ids = [result.rev_id for result in results if result.rev_id is not None]
            conn.execute(
                "UPDATE verification_case SET state='resolved', result_rev_ids_json=?,"
                " result_json=?, lease_owner=NULL, lease_until=NULL, last_error=NULL,"
                " updated_at=? WHERE case_id=?",
                (json_field(result_rev_ids), json_field(decision), utc_now(), case_id),
            )
            return "resolved", results

    def verification_cursor(self, detector: str = "default") -> int:
        row = (
            self._conn()
            .execute("SELECT through_rev FROM verification_cursor WHERE detector=?", (detector,))
            .fetchone()
        )
        return int(row["through_rev"]) if row else 0

    def set_verification_cursor(self, through_rev: int, detector: str = "default") -> None:
        with self._write_txn() as conn:
            conn.execute(
                "INSERT INTO verification_cursor(detector, through_rev, updated_at)"
                " VALUES (?,?,?) ON CONFLICT(detector) DO UPDATE SET"
                " through_rev=excluded.through_rev, updated_at=excluded.updated_at",
                (detector, int(through_rev), utc_now()),
            )

    def cached_verification_decision(self, decision_input_hash: str) -> dict[str, Any] | None:
        row = (
            self._conn()
            .execute(
                "SELECT result_json FROM verification_decision_cache WHERE decision_input_hash=?",
                (decision_input_hash,),
            )
            .fetchone()
        )
        if row is None:
            return None
        try:
            return json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            return None

    def cache_verification_decision(self, decision_input_hash: str, result: dict[str, Any]) -> None:
        with self._write_txn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO verification_decision_cache("
                " decision_input_hash, result_json, created_at) VALUES (?,?,?)",
                (decision_input_hash, json_field(result), utc_now()),
            )

    def verification_stats(self) -> dict[str, Any]:
        conn = self._conn()
        counts = {
            row["state"]: int(row["c"])
            for row in conn.execute(
                "SELECT state, COUNT(*) AS c FROM verification_case GROUP BY state"
            ).fetchall()
        }
        oldest = conn.execute(
            "SELECT MIN(created_at) AS value FROM verification_case"
            " WHERE state IN ('waiting_evidence','pending','running','needs_review')"
        ).fetchone()["value"]
        return {
            "case_counts": counts,
            "oldest_opened_at": oldest,
            "cursor_through_rev": self.verification_cursor(),
            "lag": max(0, self.max_rev_id() - self.verification_cursor()),
        }

    # ── Time travel and rollback ────────────────────────────────────────

    def as_of(
        self,
        *,
        rev_id: int | None = None,
        timestamp: str | None = None,
        user_id: str | None = None,
    ) -> list[Revision]:
        """Time-travel read: rebuild the head set at some point in time.

        Filters out revisions recorded after that point and takes the maximum remaining rev_id for
        each crystal. It modifies no data -- this is a pure query.

        rev_id is an exact cursor (globally monotonic, doubling as a logical clock); timestamp's
        resolution is limited by wall-clock granularity (~15ms on Windows), so multiple revisions
        written in the same instant are included together by the `<=`. Use rev_id for precise cuts.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if rev_id is not None:
            clauses.append("rev_id <= ?")
            params.append(int(rev_id))
        if timestamp:
            clauses.append("recorded_at <= ?")
            params.append(timestamp)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT {_REVISION_COLUMNS} FROM crystal_revision WHERE rev_id IN ("
            f"  SELECT MAX(rev_id) FROM crystal_revision{where} GROUP BY crystal_id"
            ") ORDER BY crystal_id"
        )
        rows = self._conn().execute(sql, params).fetchall()
        revisions = [Revision.from_row(row) for row in rows]
        if user_id is not None:
            revisions = [rev for rev in revisions if rev.scope.get("user_id") == user_id]
        return revisions

    def rollback_crystal(
        self, crystal_id: str, *, version: int | None = None, rev_id: int | None = None
    ) -> Head:
        """Entry-level rollback: only moves the pointer, leaves history data untouched byte-for-byte."""
        if version is None and rev_id is None:
            raise LedgerError("rollback_crystal 需要 version 或 rev_id 之一")
        with self._write_txn() as conn:
            if rev_id is not None:
                row = conn.execute(
                    "SELECT rev_id FROM crystal_revision WHERE crystal_id = ? AND rev_id = ?",
                    (crystal_id, int(rev_id)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT rev_id FROM crystal_revision WHERE crystal_id = ? AND version = ?"
                    " ORDER BY rev_id DESC LIMIT 1",
                    (crystal_id, int(version)),
                ).fetchone()
            if row is None:
                raise LedgerError(
                    f"rollback_crystal: crystal {crystal_id} 无匹配修订"
                    f" (version={version}, rev_id={rev_id})"
                )
            target = int(row["rev_id"])
            now = utc_now()
            conn.execute(
                "INSERT INTO crystal_head(crystal_id, rev_id, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(crystal_id) DO UPDATE SET rev_id=excluded.rev_id,"
                " updated_at=excluded.updated_at",
                (crystal_id, target, now),
            )
            conn.execute(
                "DELETE FROM crystal_head_detachment WHERE crystal_id = ?",
                (crystal_id,),
            )
        logger.info("固化层: 条目级回滚 crystal=%s → rev=%d", crystal_id[:12], target)
        return Head(crystal_id=crystal_id, rev_id=target, updated_at=now)

    def rollback_batch(self, batch_id: str) -> dict[str, Any]:
        """Batch-level rollback: reset each crystal's head touched by the batch to its pre-batch state.

        Crystals with no revision before the batch (i.e. created by the batch) are removed from the
        head table -- their ledger stream is still fully preserved, only the active pointer is gone.
        """
        with self._write_txn() as conn:
            affected = [
                row["crystal_id"]
                for row in conn.execute(
                    "SELECT DISTINCT crystal_id FROM crystal_revision WHERE batch_id = ?",
                    (batch_id,),
                ).fetchall()
            ]
            if not affected:
                return {"batch_id": batch_id, "affected": 0, "reverted": [], "detached": []}

            now = utc_now()
            reverted: list[dict[str, Any]] = []
            detached: list[str] = []
            for crystal_id in affected:
                row = conn.execute(
                    "SELECT MAX(rev_id) AS m FROM crystal_revision"
                    " WHERE crystal_id = ? AND batch_id != ?"
                    "   AND rev_id < (SELECT MIN(rev_id) FROM crystal_revision"
                    "                 WHERE crystal_id = ? AND batch_id = ?)",
                    (crystal_id, batch_id, crystal_id, batch_id),
                ).fetchone()
                target = row["m"] if row else None
                if target is None:
                    conn.execute("DELETE FROM crystal_head WHERE crystal_id = ?", (crystal_id,))
                    conn.execute(
                        "INSERT INTO crystal_head_detachment(crystal_id, batch_id, updated_at)"
                        " VALUES (?,?,?) ON CONFLICT(crystal_id) DO UPDATE SET"
                        " batch_id=excluded.batch_id, updated_at=excluded.updated_at",
                        (crystal_id, batch_id, now),
                    )
                    detached.append(crystal_id)
                else:
                    conn.execute(
                        "INSERT INTO crystal_head(crystal_id, rev_id, updated_at) VALUES (?,?,?)"
                        " ON CONFLICT(crystal_id) DO UPDATE SET rev_id=excluded.rev_id,"
                        " updated_at=excluded.updated_at",
                        (crystal_id, int(target), now),
                    )
                    conn.execute(
                        "DELETE FROM crystal_head_detachment WHERE crystal_id = ?",
                        (crystal_id,),
                    )
                    reverted.append({"crystal_id": crystal_id, "rev_id": int(target)})

        logger.info(
            "固化层: 批次级回滚 batch=%s, 回退 %d 条, 摘除 %d 条",
            batch_id,
            len(reverted),
            len(detached),
        )
        return {
            "batch_id": batch_id,
            "affected": len(affected),
            "reverted": reverted,
            "detached": detached,
        }

    def rebuild_heads(self) -> dict[str, Any]:
        """Rebuild crystal_head by fully replaying the ledger.

        head is the only mutable state, and therefore the only thing that can be corrupted. This
        method is a startup check: it compares existing heads against the ledger-derived result,
        reports differences and repairs them.
        Pointers produced by rollback are also "repaired" back to the max rev, so only call this
        when corruption is detected, or use verify_heads() (dry_run semantics) for a read-only
        comparison.
        """
        with self._write_txn() as conn:
            detached = {
                row["crystal_id"]
                for row in conn.execute("SELECT crystal_id FROM crystal_head_detachment").fetchall()
            }
            derived = {
                row["crystal_id"]: int(row["m"])
                for row in conn.execute(
                    "SELECT crystal_id, MAX(rev_id) AS m FROM crystal_revision GROUP BY crystal_id"
                ).fetchall()
                if row["crystal_id"] not in detached
            }
            existing = {
                row["crystal_id"]: int(row["rev_id"])
                for row in conn.execute("SELECT crystal_id, rev_id FROM crystal_head").fetchall()
            }
            now = utc_now()
            repaired: list[str] = []
            for crystal_id, rev_id in derived.items():
                if existing.get(crystal_id) != rev_id:
                    conn.execute(
                        "INSERT INTO crystal_head(crystal_id, rev_id, updated_at) VALUES (?,?,?)"
                        " ON CONFLICT(crystal_id) DO UPDATE SET rev_id=excluded.rev_id,"
                        " updated_at=excluded.updated_at",
                        (crystal_id, rev_id, now),
                    )
                    repaired.append(crystal_id)
            orphans = [cid for cid in existing if cid not in derived]
            for crystal_id in orphans:
                conn.execute("DELETE FROM crystal_head WHERE crystal_id = ?", (crystal_id,))

        return {
            "crystals": len(derived),
            "repaired": len(repaired),
            "orphans_removed": len(orphans),
        }

    def verify_heads(self) -> dict[str, Any]:
        """Read-only check: are heads consistent with the ledger-derived result? Modifies nothing.

        Difference from rebuild_heads: a pointer after rollback appears here as "behind", which is
        normal, so the three categories of difference (missing / orphan / behind) are returned for
        the caller to judge.
        """
        conn = self._conn()
        derived = {
            row["crystal_id"]: int(row["m"])
            for row in conn.execute(
                "SELECT crystal_id, MAX(rev_id) AS m FROM crystal_revision GROUP BY crystal_id"
            ).fetchall()
        }
        existing = {
            row["crystal_id"]: int(row["rev_id"])
            for row in conn.execute("SELECT crystal_id, rev_id FROM crystal_head").fetchall()
        }
        detached = sorted(
            row["crystal_id"]
            for row in conn.execute(
                "SELECT crystal_id FROM crystal_head_detachment ORDER BY crystal_id"
            ).fetchall()
        )
        detached_set = set(detached)
        missing = sorted(cid for cid in derived if cid not in existing and cid not in detached_set)
        orphans = sorted(cid for cid in existing if cid not in derived)
        behind = sorted(
            cid for cid, rev in existing.items() if cid in derived and rev < derived[cid]
        )
        ahead = sorted(
            cid for cid, rev in existing.items() if cid in derived and rev > derived[cid]
        )
        return {
            "crystals": len(derived),
            "heads": len(existing),
            "missing_heads": missing,
            "detached_heads": detached,
            "orphan_heads": orphans,
            "behind_heads": behind,
            "ahead_heads": ahead,
            "consistent": not (missing or orphans or ahead),
        }

    # ── Projection watermark ─────────────────────────────────────────────

    def projection_state(self) -> dict[str, dict[str, Any]]:
        rows = (
            self._conn()
            .execute("SELECT projection, through_rev, updated_at FROM projection_state")
            .fetchall()
        )
        return {
            row["projection"]: {
                "through_rev": int(row["through_rev"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def set_projection_through(self, projection: str, through_rev: int) -> None:
        with self._write_txn() as conn:
            conn.execute(
                "INSERT INTO projection_state(projection, through_rev, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(projection) DO UPDATE SET through_rev=excluded.through_rev,"
                " updated_at=excluded.updated_at",
                (projection, int(through_rev), utc_now()),
            )

    # ── Stats and operations ─────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Ledger summary: revision count, crystal count, status distribution, op distribution, watermark."""
        conn = self._conn()
        revisions = int(conn.execute("SELECT COUNT(*) AS c FROM crystal_revision").fetchone()["c"])
        crystals = int(conn.execute("SELECT COUNT(*) AS c FROM crystal_head").fetchone()["c"])
        by_status = {
            row["status"]: int(row["c"])
            for row in conn.execute(
                "SELECT r.status, COUNT(*) AS c FROM crystal_revision r"
                " JOIN crystal_head h ON h.rev_id = r.rev_id GROUP BY r.status"
            ).fetchall()
        }
        by_op = {
            row["op"]: int(row["c"])
            for row in conn.execute(
                "SELECT op, COUNT(*) AS c FROM crystal_revision GROUP BY op"
            ).fetchall()
        }
        edges = int(conn.execute("SELECT COUNT(*) AS c FROM crystal_edge").fetchone()["c"])
        lineage = int(conn.execute("SELECT COUNT(*) AS c FROM crystal_lineage").fetchone()["c"])
        detached = int(
            conn.execute("SELECT COUNT(*) AS c FROM crystal_head_detachment").fetchone()["c"]
        )
        return {
            "db_path": self._db_path,
            "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
            "revisions": revisions,
            "crystals": crystals,
            "max_rev_id": self.max_rev_id(),
            "head_status_counts": by_status,
            "op_counts": by_op,
            "edges": edges,
            "lineage_links": lineage,
            "detached_heads": detached,
            "projections": self.projection_state(),
        }

    def reset(self) -> dict[str, Any]:
        """Clear all ledger data (for factory reset). Keeps table structure and watermark rows."""
        before = {
            "revisions": int(
                self._conn().execute("SELECT COUNT(*) AS c FROM crystal_revision").fetchone()["c"]
            ),
            "crystals": int(
                self._conn().execute("SELECT COUNT(*) AS c FROM crystal_head").fetchone()["c"]
            ),
        }
        with self._write_txn() as conn:
            # Delete referrers first, then referents, to satisfy foreign_keys=ON
            for table in (
                "verification_evidence",
                "verification_decision_cache",
                "verification_case",
                "verification_cursor",
                "crystal_head",
                "crystal_head_detachment",
                "crystal_edge",
                "crystal_lineage",
                "crystal_revision",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ("
                "'crystal_revision','crystal_edge','verification_evidence')"
            )
            now = utc_now()
            for projection in schema.PROJECTIONS:
                conn.execute(
                    "INSERT INTO projection_state(projection, through_rev, updated_at)"
                    " VALUES (?,0,?) ON CONFLICT(projection) DO UPDATE SET through_rev=0,"
                    " updated_at=excluded.updated_at",
                    (projection, now),
                )
        logger.info(
            "固化层: 账本重置完成, 清除 %d 条修订 / %d 个结晶",
            before["revisions"],
            before["crystals"],
        )
        return before
