"""JSON-based board store — BoardEnvelope + payload hash chain + idempotency +
revision CAS + corruption recovery.

Spec §7.3 — BoardEnvelope on-disk format
Spec §5.1.1 — RevisionVector
Spec §5.10 — command idempotency + revision CAS
Spec §7.5 — atomic-write protocol (delegates to atomic_file)
Spec §7.6 — execute_atomic two-phase (lock → re-read → validate → mutate → write)
Spec §7.12 — corruption recovery

This module imports nothing from ToolContext or Task-v2 (spec §11.4 inv 12).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import time
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .atomic_file import BoardStoreIOError, atomic_write_json
from .commands import CommandResult
from .graph_types import (
    Board,
    BoardPolicy,
    Claim,
    Graph,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    RevisionVector,
)
from .ir_hash import canonical_hash
from .refs import NodeRef

# ── error types ───────────────────────────────────────────────────────


class BoardStoreCorruptError(Exception):
    """Raised when both board.json and board.json.bak are unreadable/invalid.

    Per spec §7.12, the store NEVER returns an empty Board when both files
    are corrupt — callers must get a clear error and handle recovery
    explicitly (quarantine, doctor, restore from history, etc.).
    """


class BoardRecoveryWarning(UserWarning):
    """Visible warning emitted after an automatic backup recovery."""


class StaleRevisionError(Exception):
    """Raised when expected_revision_vector CAS check fails (LKB-STORE-006/007).

    The caller's snapshot was taken at a revision that no longer matches
    the current state for at least one graph.  Callers should re-read and
    retry, or surface the conflict to the user.
    """

    def __init__(
        self,
        board_id: str,
        expected: RevisionVector,
        actual: RevisionVector,
        *,
        reason: str = "",
    ) -> None:
        self.board_id = board_id
        self.expected = expected
        self.actual = actual
        msg = (
            f"Stale revision for board {board_id!r}: "
            f"expected {expected.to_dict()}, actual {actual.to_dict()}"
        )
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class IdempotencyKeyReusedError(Exception):
    """Raised when a command_id is reused with a different request_hash
    (LKB-STORE-005).

    The same command_id was previously committed with a different command
    payload.  Callers must pick a new command_id if they intend a new
    command — reusing the id with different content is forbidden.
    """

    def __init__(
        self,
        command_id: str,
        stored_request_hash: str,
        new_request_hash: str,
    ) -> None:
        self.command_id = command_id
        self.stored_request_hash = stored_request_hash
        self.new_request_hash = new_request_hash
        super().__init__(
            f"Idempotency key {command_id!r} reused with different request hash: "
            f"stored={stored_request_hash}, new={new_request_hash}"
        )


class BoardSchemaTooNewError(Exception):
    """Raised when the on-disk schema_version is newer than this code knows.

    This prevents an older reader from silently corrupting a board written
    by a newer version (LKB-STORE-025 / forward-compatibility guard).
    """

    def __init__(self, board_id: str, on_disk: int, supported: int) -> None:
        self.board_id = board_id
        self.on_disk_version = on_disk
        self.supported_version = supported
        super().__init__(
            f"Board {board_id!r} has schema_version={on_disk}, "
            f"but this build only supports up to {supported}"
        )


class BoardNotFoundError(Exception):
    """Raised when a board directory or board.json does not exist."""

    def __init__(self, board_id: str, path: Path) -> None:
        self.board_id = board_id
        self.path = path
        super().__init__(f"Board {board_id!r} not found at {path}")


class BoardTombstonedError(BoardNotFoundError):
    """Raised when a Tombstone forbids loading or recreating a purged Board."""

    def __init__(self, board_id: str, path: Path) -> None:
        self.tombstone_path = path
        super().__init__(board_id, path)


# ── constants ─────────────────────────────────────────────────────────

STORE_FORMAT = "lkb-json-v1"
CURRENT_SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"


def _now_iso() -> str:
    """Current UTC time in ISO-8601 for audit event timestamps (spec §6.10)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Keys in the top-level envelope, in canonical (sorted) order.
_ENVELOPE_TOP_KEYS = (
    "assertions",
    "board",
    "claims",
    "edges",
    "events",
    "evidence",
    "graphs",
    "historySegments",
    "integrity",
    "lifecycle",
    "nodes",
    "processedCommands",
    "schemaVersion",
    "storeFormat",
    "storeRevision",
    "validationRuns",
)


# ── BoardEnvelope ─────────────────────────────────────────────────────


@dataclass
class BoardEnvelope:
    """On-disk JSON envelope for a board (spec §7.3).

    The envelope holds *every* piece of board state — board metadata,
    graphs, nodes, edges, claims, assertions, evidence, validation runs,
    processed-command log, events, history segments, lifecycle state, and
    the integrity block (payload hash chain).

    All collection fields are plain dicts keyed by stable identifiers so
    that canonical JSON (sorted keys) produces a deterministic hash.
    """

    store_format: str = STORE_FORMAT
    schema_version: int = CURRENT_SCHEMA_VERSION
    store_revision: int = 0

    # Core board metadata (dict form — Board is reconstructed on load).
    board: dict[str, Any] = field(default_factory=dict)

    # Collections: {id -> record_dict}
    graphs: dict[str, dict[str, Any]] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    assertions: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    validation_runs: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Processed commands: {command_id -> {request_hash, decision, ...}}
    processed_commands: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Event log (append-only list).
    events: list[dict[str, Any]] = field(default_factory=list)

    # History segment references.
    history_segments: list[dict[str, Any]] = field(default_factory=list)

    # Lifecycle state (active | closed | archived | trashed).
    lifecycle: dict[str, Any] = field(default_factory=dict)

    # Integrity block.  payload_hash and previous_payload_hash form the
    # revision chain; algorithm names the hash function used.
    integrity: dict[str, Any] = field(default_factory=dict)

    # ── serialization ─────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a stable-key-ordered dict.

        Keys match the on-disk camelCase convention (spec §7.3).
        """
        return {
            "storeFormat": self.store_format,
            "schemaVersion": self.schema_version,
            "storeRevision": self.store_revision,
            "board": self.board,
            "graphs": self.graphs,
            "nodes": self.nodes,
            "edges": self.edges,
            "claims": self.claims,
            "assertions": self.assertions,
            "evidence": self.evidence,
            "validationRuns": self.validation_runs,
            "processedCommands": self.processed_commands,
            "events": list(self.events),
            "historySegments": list(self.history_segments),
            "lifecycle": self.lifecycle,
            "integrity": self.integrity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BoardEnvelope":
        """Deserialize from a dict (e.g. parsed JSON).

        This decoder is deliberately strict.  Migration code must first
        transform older envelopes into the current complete shape; silently
        defaulting missing fields here would make corruption look like valid
        empty state.
        """
        if not isinstance(data, dict):
            raise ValueError("envelope is not a JSON object")
        missing = set(_ENVELOPE_TOP_KEYS) - set(data)
        extra = set(data) - set(_ENVELOPE_TOP_KEYS)
        if missing:
            raise ValueError(f"envelope is missing required fields: {sorted(missing)}")
        if extra:
            raise ValueError(f"envelope has unknown fields: {sorted(extra)}")
        return cls(
            store_format=data["storeFormat"],
            schema_version=data["schemaVersion"],
            store_revision=data["storeRevision"],
            board=copy.deepcopy(data["board"]),
            graphs=copy.deepcopy(data["graphs"]),
            nodes=copy.deepcopy(data["nodes"]),
            edges=copy.deepcopy(data["edges"]),
            claims=copy.deepcopy(data["claims"]),
            assertions=copy.deepcopy(data["assertions"]),
            evidence=copy.deepcopy(data["evidence"]),
            validation_runs=copy.deepcopy(data["validationRuns"]),
            processed_commands=copy.deepcopy(data["processedCommands"]),
            events=copy.deepcopy(data["events"]),
            history_segments=copy.deepcopy(data["historySegments"]),
            lifecycle=copy.deepcopy(data["lifecycle"]),
            integrity=copy.deepcopy(data["integrity"]),
        )

    # ── derived views ─────────────────────────────────────────────────

    def board_id(self) -> str:
        return str(self.board.get("board_id", ""))

    def current_revision_vector(self) -> RevisionVector:
        """Build a RevisionVector from graph revisions."""
        revs: dict[str, int] = {}
        for gid, g in self.graphs.items():
            revs[gid] = int(g.get("revision", 0))
        return RevisionVector(revisions=revs)

    def build_graph_snapshot(self) -> GraphSnapshot:
        """Reconstruct a GraphSnapshot from the envelope contents."""
        graphs: dict[str, Graph] = {}
        for gid, g in self.graphs.items():
            graphs[gid] = Graph(
                graph_id=str(g.get("graph_id", gid)),
                board_id=str(g.get("board_id", self.board_id())),
                graph_kind=str(g.get("graph_kind", "")),
                revision=int(g.get("revision", 0)),
                created_at=str(g.get("created_at", "")),
                updated_at=str(g.get("updated_at", "")),
                metadata=copy.deepcopy(g.get("plan", {}))
                if isinstance(g.get("plan"), dict)
                else {},
            )

        nodes: dict[NodeRef, GraphNode] = {}
        for _nid, n in self.nodes.items():
            ref_str = str(n.get("ref", ""))
            ref = NodeRef.from_str(ref_str)
            nodes[ref] = GraphNode(
                ref=ref,
                title=str(n.get("title", "")),
                state=n.get("state"),
                owner=n.get("owner"),
                revision=int(n.get("revision", 0)),
                payload=dict(n.get("payload", {})),
                created_at=str(n.get("created_at", "")),
                updated_at=str(n.get("updated_at", "")),
            )

        edges: dict[str, GraphEdge] = {}
        for eid, e in self.edges.items():
            src = NodeRef.from_str(str(e.get("source", "")))
            tgt = NodeRef.from_str(str(e.get("target", "")))
            edges[eid] = GraphEdge(
                edge_id=str(e.get("edge_id", eid)),
                graph=str(e.get("graph", "")),
                type=str(e.get("type", "")),
                source=src,
                target=tgt,
                revision=int(e.get("revision", 0)),
                payload=dict(e.get("payload", {})),
            )

        rv = self.current_revision_vector()
        board_dict = self.board if isinstance(self.board, dict) else {}
        policy_dict = board_dict.get("policy") if isinstance(board_dict.get("policy"), dict) else {}
        snap = GraphSnapshot(
            board_id=self.board_id(),
            store_revision=self.store_revision,
            graphs=graphs,
            nodes=nodes,
            edges=edges,
            revision_vector=rv,
            policy=copy.deepcopy(policy_dict),
        )
        return snap

    def clone(self) -> "BoardEnvelope":
        """Return a deep copy (mutations on clone don't touch original)."""
        return BoardEnvelope.from_dict(copy.deepcopy(self.to_dict()))


# ── payload hash chain ────────────────────────────────────────────────


def payload_hash(envelope: BoardEnvelope, *, algorithm: str = HASH_ALGORITHM) -> str:
    """Compute the payload hash of *envelope* (spec §7.3).

    The ``integrity`` block is stripped before hashing — the hash cannot
    include itself.  Returns ``"sha256:<hex>"`` (or the requested
    algorithm prefix).
    """
    data = envelope.to_dict()
    data.pop("integrity", None)
    return canonical_hash(data, algorithm=algorithm)


def set_payload_hash(
    envelope: BoardEnvelope,
    *,
    previous_hash: str | None = None,
    algorithm: str = HASH_ALGORITHM,
) -> str:
    """Compute and set ``integrity.payloadHash`` on *envelope* in place.

    If *previous_hash* is given, sets ``integrity.previousPayloadHash``
    to form the chain (spec §7.3).  Returns the computed payload hash.
    """
    # Strip integrity first, compute the hash, then set both fields.
    envelope.integrity = {}
    h = payload_hash(envelope, algorithm=algorithm)
    envelope.integrity = {
        "algorithm": algorithm,
        "payloadHash": h,
    }
    if previous_hash is not None:
        envelope.integrity["previousPayloadHash"] = previous_hash
    return h


# ── schema validation ─────────────────────────────────────────────────


def _validate_envelope_schema(
    data: dict[str, Any],
    *,
    board_id: str | None = None,
) -> None:
    """Lightweight schema validation of a raw envelope dict.

    Checks store format, schema version range, required board fields,
    and board_id match (if *board_id* is provided).  Raises
    ``ValueError`` on any problem.
    """
    if not isinstance(data, dict):
        raise ValueError("envelope is not a JSON object")
    missing = set(_ENVELOPE_TOP_KEYS) - set(data)
    extra = set(data) - set(_ENVELOPE_TOP_KEYS)
    if missing:
        raise ValueError(f"envelope is missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"envelope has unknown fields: {sorted(extra)}")

    store_fmt = data.get("storeFormat")
    if store_fmt != STORE_FORMAT:
        raise ValueError(f"unexpected storeFormat: {store_fmt!r}")

    schema_ver = data.get("schemaVersion")
    if not isinstance(schema_ver, int) or schema_ver < 1:
        raise ValueError(f"invalid schemaVersion: {schema_ver!r}")
    if schema_ver > CURRENT_SCHEMA_VERSION:
        raise BoardSchemaTooNewError(
            str(data.get("board", {}).get("board_id", "?")),
            schema_ver,
            CURRENT_SCHEMA_VERSION,
        )

    board = data.get("board")
    if not isinstance(board, dict):
        raise ValueError("board field is missing or not an object")
    if not board.get("board_id"):
        raise ValueError("board.board_id is missing or empty")

    store_rev = data.get("storeRevision")
    if not isinstance(store_rev, int) or store_rev < 0:
        raise ValueError(f"invalid storeRevision: {store_rev!r}")

    if board_id is not None and board.get("board_id") != board_id:
        raise ValueError(
            f"board_id mismatch: envelope has {board.get('board_id')!r}, expected {board_id!r}"
        )

    # Collections are required and must be dictionaries.
    for key in (
        "graphs",
        "nodes",
        "edges",
        "claims",
        "assertions",
        "evidence",
        "validationRuns",
        "processedCommands",
    ):
        if not isinstance(data[key], dict):
            raise ValueError(f"{key} is not a dict")

    for key in ("events", "historySegments"):
        if not isinstance(data[key], list):
            raise ValueError(f"{key} is not a list")
        if not all(isinstance(item, dict) for item in data[key]):
            raise ValueError(f"{key} contains a non-object record")
    if not isinstance(data["lifecycle"], dict):
        raise ValueError("lifecycle is not an object")

    # Integrity block must be present and have payloadHash.
    integrity = data.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("integrity block is missing or not an object")
    if not integrity.get("payloadHash"):
        raise ValueError("integrity.payloadHash is missing or empty")
    if integrity.get("algorithm", HASH_ALGORITHM) != HASH_ALGORITHM:
        raise ValueError(f"unsupported integrity algorithm: {integrity.get('algorithm')!r}")
    if not isinstance(integrity["payloadHash"], str):
        raise ValueError("integrity.payloadHash is not a string")

    _assert_envelope_invariants(data)


def _parse_ref(value: Any, *, location: str) -> NodeRef:
    if not isinstance(value, str):
        raise ValueError(f"{location} must be a NodeRef string")
    try:
        return NodeRef.from_str(value)
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"{location} is not a valid NodeRef: {value!r}") from exc


def _assert_envelope_invariants(data: dict[str, Any]) -> None:
    """Validate all graph-store invariants available in the v1 envelope."""
    board_id = data["board"]["board_id"]
    graphs = data["graphs"]
    nodes = data["nodes"]
    edges = data["edges"]

    for gid, graph in graphs.items():
        if not isinstance(gid, str) or not gid or not isinstance(graph, dict):
            raise ValueError(f"invalid graph record {gid!r}")
        if graph.get("graph_id") != gid:
            raise ValueError(f"graph key/id mismatch for {gid!r}")
        if graph.get("board_id") != board_id:
            raise ValueError(f"graph {gid!r} belongs to another board")
        if not isinstance(graph.get("graph_kind"), str) or not graph["graph_kind"]:
            raise ValueError(f"graph {gid!r} has invalid graph_kind")
        revision = graph.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError(f"graph {gid!r} has invalid revision")

    refs: dict[NodeRef, str] = {}
    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            raise ValueError(f"invalid node record {node_id!r}")
        ref = _parse_ref(node.get("ref"), location=f"nodes[{node_id!r}].ref")
        if ref in refs:
            raise ValueError(f"duplicate NodeRef {ref.to_str()!r} in {refs[ref]!r} and {node_id!r}")
        if ref.graph not in graphs:
            raise ValueError(f"node {ref.to_str()!r} refers to missing graph")
        refs[ref] = node_id
        revision = node.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError(f"node {ref.to_str()!r} has invalid revision")
        if "payload" in node and not isinstance(node["payload"], dict):
            raise ValueError(f"node {ref.to_str()!r} payload is not an object")

    adjacency: dict[NodeRef, set[NodeRef]] = {ref: set() for ref in refs}
    for edge_id, edge in edges.items():
        if not isinstance(edge_id, str) or not isinstance(edge, dict):
            raise ValueError(f"invalid edge record {edge_id!r}")
        if edge.get("edge_id") != edge_id:
            raise ValueError(f"edge key/id mismatch for {edge_id!r}")
        graph_id = edge.get("graph")
        if graph_id not in graphs:
            raise ValueError(f"edge {edge_id!r} refers to missing graph")
        source = _parse_ref(edge.get("source"), location=f"edges[{edge_id!r}].source")
        target = _parse_ref(edge.get("target"), location=f"edges[{edge_id!r}].target")
        if source == target:
            raise ValueError(f"edge {edge_id!r} is a self-dependency")
        if source not in refs or target not in refs:
            raise ValueError(f"edge {edge_id!r} has a dangling endpoint")
        if source.graph != graph_id or target.graph != graph_id:
            raise ValueError(f"edge {edge_id!r} crosses its declared graph")
        revision = edge.get("revision", 0)
        if not isinstance(revision, int) or revision < 0:
            raise ValueError(f"edge {edge_id!r} has invalid revision")
        if edge.get("type") == "depends_on":
            adjacency[source].add(target)

    visiting: set[NodeRef] = set()
    visited: set[NodeRef] = set()

    def visit(ref: NodeRef) -> None:
        if ref in visiting:
            raise ValueError(f"dependency cycle includes {ref.to_str()!r}")
        if ref in visited:
            return
        visiting.add(ref)
        for target in adjacency[ref]:
            visit(target)
        visiting.remove(ref)
        visited.add(ref)

    for ref in adjacency:
        visit(ref)

    active_claims: set[NodeRef] = set()
    for claim_id, claim in data["claims"].items():
        if not isinstance(claim_id, str) or not isinstance(claim, dict):
            raise ValueError(f"invalid claim record {claim_id!r}")
        if claim.get("claim_id", claim_id) != claim_id:
            raise ValueError(f"claim key/id mismatch for {claim_id!r}")
        task_ref = _parse_ref(claim.get("task_ref"), location=f"claims[{claim_id!r}].task_ref")
        if task_ref not in refs:
            raise ValueError(f"claim {claim_id!r} refers to a missing task")
        # Spec §5.6 / issue #10: owner_ref is a NodeRef (plan:agent:<actor>),
        # never a bare actor string.  Validate the format and, for active
        # claims, that the owner_ref.id matches the task node's owner field
        # (Claim/Projection bidirectional consistency).
        owner_ref = _parse_ref(claim.get("owner_ref"), location=f"claims[{claim_id!r}].owner_ref")
        if owner_ref.kind != "agent":
            raise ValueError(
                f"claim {claim_id!r} owner_ref {owner_ref.to_str()!r} is not an agent NodeRef"
            )
        claim_revision = claim.get("claim_revision")
        if (
            not isinstance(claim_revision, int)
            or isinstance(claim_revision, bool)
            or claim_revision < 0
        ):
            raise ValueError(f"claim {claim_id!r} has no real claim_revision")
        if claim.get("status", "active") == "active":
            if task_ref in active_claims:
                raise ValueError(f"multiple active claims for {task_ref.to_str()!r}")
            task_node = nodes[refs[task_ref]]
            if task_node.get("state") in {"blocked", "completed", "needs_recheck"}:
                raise ValueError(
                    f"active claim {claim_id!r} targets non-claimable "
                    f"state {task_node.get('state')!r}"
                )
            node_owner = task_node.get("owner")
            if not isinstance(node_owner, str) or not node_owner:
                raise ValueError(f"active claim {claim_id!r} targets task with no owner field")
            if owner_ref.id != node_owner:
                raise ValueError(
                    f"active claim {claim_id!r} owner_ref {owner_ref.to_str()!r} "
                    f"disagrees with task node owner {node_owner!r}"
                )
            active_claims.add(task_ref)

    for collection_name in ("assertions", "evidence"):
        for record_id, record in data[collection_name].items():
            if not isinstance(record_id, str) or not isinstance(record, dict):
                raise ValueError(f"invalid {collection_name} record {record_id!r}")
            graph_ids = _record_graph_ids(record)
            if not graph_ids:
                raise ValueError(f"{collection_name}[{record_id!r}] has no subject NodeRef")
            if not graph_ids <= set(graphs):
                raise ValueError(f"{collection_name}[{record_id!r}] refers to a missing graph")

    for name in ("validationRuns", "processedCommands"):
        for record_id, record in data[name].items():
            if not isinstance(record_id, str) or not isinstance(record, dict):
                raise ValueError(f"invalid {name} record {record_id!r}")


def _verify_payload_hash(data: dict[str, Any]) -> bool:
    """Return True if the payload hash in *data* matches the content.

    Strips the integrity block, hashes the rest, and compares.
    """
    integrity = data.get("integrity", {})
    expected = integrity.get("payloadHash", "")
    if not expected:
        return False

    payload = {k: v for k, v in data.items() if k != "integrity"}
    actual = canonical_hash(payload)
    return actual == expected


def _verify_revision_chain(
    data: dict[str, Any],
    previous_payload_hash: str | None,
) -> bool:
    """Check that ``integrity.previousPayloadHash`` matches *previous_payload_hash*.

    Returns True on match or when there is no previous (store_revision == 0).
    """
    store_rev = data.get("storeRevision", 0)
    if store_rev == 0:
        # Genesis revision — no previous expected.
        return True
    if previous_payload_hash is None:
        # We have no prior hash to compare against — chain unverifiable but
        # not necessarily broken.  Caller decides.
        return True
    actual_prev = data.get("integrity", {}).get("previousPayloadHash", "")
    return actual_prev == previous_payload_hash


# ── JsonBoardStore ────────────────────────────────────────────────────


class JsonBoardStore:
    """Crash-consistent JSON board store (spec §7.3 – §7.6, §7.12).

    Responsibilities:
    * Load / validate board envelopes from disk
    * Execute atomic mutations under a BoardFileLock (two-phase)
    * Idempotency via ``processedCommands`` (LKB-STORE-004/005)
    * Revision CAS via ``expected_revision_vector`` (LKB-STORE-006/007)
    * Corruption recovery via .bak rotation (spec §7.12)

    Parameters
    ----------
    board_dir:
        Path to the board directory (contains board.json, .lock, etc.).
    board_id:
        Expected board_id — re-validated on every load (LKB-STORE-028).
    lock:
        A ``BoardFileLock`` instance (or compatible context manager)
        that provides exclusive cross-process + thread access.
    home:
        Optional home directory override (for diagnostics only).
    failpoint:
        Optional ``Failpoint`` for crash-injection testing.
    """

    def __init__(
        self,
        board_dir: Path | str,
        *,
        board_id: str,
        lock: Any,
        home: Path | None = None,
        failpoint: Any | None = None,
    ) -> None:
        self._board_dir = Path(board_dir)
        self._board_id = board_id
        self._lock = lock
        self._home = home
        self._failpoint = failpoint

        self._board_json = self._board_dir / "board.json"
        self._board_json_bak = self._board_dir / "board.json.bak"
        self._tmp_dir = self._board_dir / ".tmp"
        self._quarantine_dir = self._board_dir / "quarantine"

    def _tombstone_path(self) -> Path:
        from .board_resolver import safe_board_id

        lkb_root = self._board_dir.parent.parent
        return lkb_root / "tombstones" / f"{safe_board_id(self._board_id)}.json"

    def _assert_not_tombstoned(self) -> None:
        marker = self._tombstone_path()
        if marker.is_file():
            from .lifecycle import read_tombstone

            read_tombstone(marker, expected_board_id=self._board_id)
            raise BoardTombstonedError(self._board_id, marker)

    # ── public read API ───────────────────────────────────────────────

    def load(self) -> BoardEnvelope:
        """Load the primary, or explicitly recover an invalid primary.

        A primary that is readable and hash-valid is authoritative (spec
        §7.12).  Its revision chain is then checked against any backup: a
        same-revision fork or a rollback raises ``BoardStoreCorruptError``
        and must *not* be silently recovered from.  Only an unreadable or
        hash-invalid primary falls through to ``.bak`` recovery.
        """
        self._assert_not_tombstoned()
        self._migrate_primary_if_needed()
        try:
            primary = self._read_valid_envelope(self._board_json)
        except BoardSchemaTooNewError:
            raise
        except (OSError, json.JSONDecodeError, ValueError):
            # Primary unreadable or hash-invalid - attempt .bak recovery.
            recovered = self._try_recover_from_backup()
            if recovered is not None:
                self._assert_not_tombstoned()
                return recovered
            raise BoardStoreCorruptError(
                f"Both {self._board_json} and {self._board_json_bak} are "
                f"corrupt or invalid for board {self._board_id!r}"
            ) from None
        # Primary is valid; validate its chain against the backup.  A fork
        # or rollback detected here must propagate, not trigger recovery.
        self._validate_primary_chain(primary)
        self._assert_not_tombstoned()
        return primary

    def read_snapshot(self) -> GraphSnapshot:
        """Read and validate only the authoritative primary snapshot."""
        self._assert_not_tombstoned()
        self._migrate_primary_if_needed()
        last_error: Exception | None = None
        envelope: BoardEnvelope | None = None
        for attempt in range(3):
            try:
                envelope = self._read_valid_envelope(self._board_json)
                break
            except BoardSchemaTooNewError:
                raise
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                # Transient: may have caught an in-progress atomic write.
                last_error = exc
            if attempt < 2:
                time.sleep(0.005 * (attempt + 1))
        if envelope is None:
            raise BoardStoreCorruptError(
                f"Cannot read valid primary snapshot for board {self._board_id!r}: {last_error}"
            )
        # Chain validation is not transient - a fork or rollback must
        # surface immediately rather than be retried or masked.
        self._validate_primary_chain(envelope)
        snapshot = envelope.build_graph_snapshot()
        self._assert_not_tombstoned()
        return snapshot

    def header(self) -> dict[str, Any]:
        """Return a cheap header dict for board listings.

        Reads just the first few bytes (board_id, store_revision,
        schema_version, display_name, lifecycle state) without loading
        the full envelope.
        """
        data = self._read_json_file(self._board_json)
        board = data.get("board", {}) if isinstance(data, dict) else {}
        return {
            "board_id": board.get("board_id", ""),
            "display_name": board.get("display_name", ""),
            "schema_version": data.get("schemaVersion", 0) if isinstance(data, dict) else 0,
            "store_revision": data.get("storeRevision", 0) if isinstance(data, dict) else 0,
            "lifecycle_state": (data.get("lifecycle", {}) or {}).get("state", "active")
            if isinstance(data, dict)
            else "unknown",
        }

    def exists(self) -> bool:
        """Return True if board.json exists (regardless of validity)."""
        return self._board_json.is_file()

    # ── public write API ──────────────────────────────────────────────

    def execute_atomic(
        self,
        board_id: str,
        command_id: str,
        request_hash: str,
        expected_revision_vector: RevisionVector | None,
        mutate: Callable[[BoardEnvelope], tuple[BoardEnvelope, CommandResult]],
        *,
        expected_store_revision: int | None = None,
        actor: str,
        reason: str | None = None,
        lifecycle_operation: bool = False,
        audit_context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Execute *mutate* atomically against the board (spec §7.6).

        Two-phase protocol:
          1. Acquire the board lock.
          2. Re-read and validate board.json.
          3. Check idempotency (processedCommands):
             - same command_id + same request_hash → return cached result
             - same command_id + different hash → IdempotencyKeyReusedError
          4. Check expected store/graph revision CAS guards.
          5. Call *mutate(envelope)* → (candidate, result).
          6. Validate candidate (schema + payload hash + board invariants).
          7. Bump store_revision + modified graph revisions.
          8. Append command result + validation + commit audit to candidate.
          9. Atomic write with .bak rotation.
         10. Return result.

        Parameters
        ----------
        board_id:
            Must match the store's board_id (defence-in-depth).
        command_id:
            Idempotency key.
        request_hash:
            Hash of the command payload (for idempotency check).
        expected_revision_vector:
            If provided, all graph revisions in the vector must match
            the current state (CAS check).  Graphs not mentioned in the
            vector are not checked.
        expected_store_revision:
            If provided, the board's store revision must match exactly.
        mutate:
            Callable receiving the current BoardEnvelope and returning
            ``(modified_envelope, CommandResult)``.  The envelope is a
            deep copy so the callback can mutate it freely.

        Returns
        -------
        CommandResult
            The result from *mutate* (possibly enriched with revision
            info on successful commit).

        Raises
        ------
        IdempotencyKeyReusedError
            command_id reused with different request_hash.
        StaleRevisionError
            expected_revision_vector doesn't match current state.
        BoardStoreCorruptError
            Board is unreadable and unrecoverable.
        """
        if board_id != self._board_id:
            raise ValueError(
                f"board_id mismatch: store owns {self._board_id!r}, command targets {board_id!r}"
            )

        self._assert_not_tombstoned()
        with self._lock:
            # Re-check after serialization: a purge may have published the
            # permanent marker while this caller was waiting for the lock.
            self._assert_not_tombstoned()
            # Step 2: re-read + validate (with .bak recovery)
            envelope = self._load_locked()

            # Step 3: idempotency check
            existing = envelope.processed_commands.get(command_id)
            if existing is not None:
                stored_hash = existing.get("request_hash", "")
                if stored_hash == request_hash:
                    # LKB-STORE-004: same id + same hash → cached result
                    decision = existing.get("decision", "committed")
                    rev_vec_dict = existing.get("revision_vector")
                    rev_vec = (
                        RevisionVector(revisions=dict(rev_vec_dict))
                        if isinstance(rev_vec_dict, dict)
                        else None
                    )
                    return CommandResult(
                        decision=decision,  # type: ignore[arg-type]
                        command_id=command_id,
                        revision_vector=rev_vec,
                        validation_run_id=existing.get("validation_run_id"),
                        reason=existing.get("reason"),
                        derived_facts=tuple(existing.get("derived_facts", ())),
                        claim_id=existing.get("claim_id"),
                        affected_refs=tuple(existing.get("affected_refs", ())),
                    )
                else:
                    # LKB-STORE-005: same id, different hash → reuse error
                    raise IdempotencyKeyReusedError(command_id, stored_hash, request_hash)

            if not lifecycle_operation:
                from .lifecycle import ordinary_write_denial_reason

                denial = ordinary_write_denial_reason(envelope)
                if denial is not None:
                    raise PermissionError(denial)

            # Step 4: expected revision CAS checks
            if (
                expected_store_revision is not None
                and envelope.store_revision != expected_store_revision
            ):
                current = envelope.current_revision_vector()
                raise StaleRevisionError(
                    board_id,
                    expected_revision_vector or RevisionVector(),
                    current,
                    reason=(
                        f"store revision: expected {expected_store_revision}, "
                        f"got {envelope.store_revision}"
                    ),
                )
            if expected_revision_vector is not None:
                current = envelope.current_revision_vector()
                for gid, expected_rev in expected_revision_vector.revisions.items():
                    actual_rev = current.get(gid)
                    if actual_rev != expected_rev:
                        raise StaleRevisionError(
                            board_id,
                            expected_revision_vector,
                            current,
                            reason=f"graph {gid!r}: expected rev {expected_rev}, got {actual_rev}",
                        )

            # Capture pre-mutation state for comparison
            pre_graph_revs: dict[str, int] = {
                gid: int(g.get("revision", 0)) for gid, g in envelope.graphs.items()
            }
            pre_store_rev = envelope.store_revision
            previous_hash = envelope.integrity.get("payloadHash", "")

            # Step 5: mutate
            candidate, result = mutate(envelope.clone())
            if not isinstance(candidate, BoardEnvelope):
                raise TypeError("mutate must return a BoardEnvelope candidate")
            if not isinstance(result, CommandResult):
                raise TypeError("mutate must return a CommandResult")

            # Step 6: validate candidate
            _validate_envelope_schema(candidate.to_dict(), board_id=board_id)
            # Recompute payload hash (with previous chain)
            set_payload_hash(candidate, previous_hash=previous_hash)

            # Step 7: bump revisions
            # Only bump store_revision if something actually changed
            # (denied commands may still bump for audit per §11.4 inv4 note,
            # but we let the caller decide via the candidate they return).
            #
            # Bump graph revisions for any graph that has new content.
            for gid, g in candidate.graphs.items():
                pre_rev = pre_graph_revs.get(gid, 0)
                cur_rev = int(g.get("revision", 0))
                if cur_rev == pre_rev:
                    # Graph revision unchanged by mutate — bump if the
                    # graph's nodes/edges changed.  We use a content-hash
                    # heuristic: compare node/edge counts.
                    pre_node_count = sum(
                        1
                        for n in envelope.nodes.values()
                        if n.get("graph") == gid
                        or NodeRef.from_str(str(n.get("ref", ":"))).graph == gid
                        if ":" in str(n.get("ref", ":"))
                    )
                    post_node_count = sum(
                        1 for n in candidate.nodes.values() if _node_graph(n) == gid
                    )
                    pre_edge_count = sum(
                        1 for e in envelope.edges.values() if e.get("graph") == gid
                    )
                    post_edge_count = sum(
                        1 for e in candidate.edges.values() if e.get("graph") == gid
                    )
                    if pre_node_count != post_node_count or pre_edge_count != post_edge_count:
                        g["revision"] = pre_rev + 1

            # Override heuristic/manual revisions with an exact per-graph
            # content comparison.
            pre_content = _graph_content(envelope)
            post_content = _graph_content(candidate)
            for gid, graph in candidate.graphs.items():
                old_revision = int(envelope.graphs.get(gid, {}).get("revision", 0))
                graph["revision"] = old_revision + (
                    1 if pre_content.get(gid) != post_content.get(gid) else 0
                )

            # Bump store_revision by 1
            candidate.store_revision = pre_store_rev + 1
            candidate.board["store_revision"] = candidate.store_revision

            # Step 8: append command + audit to processedCommands
            rev_vec = candidate.current_revision_vector()
            entry: dict[str, Any] = {
                "command_id": command_id,
                "request_hash": request_hash,
                "decision": result.decision,
                "actor": actor,
                "store_revision": candidate.store_revision,
                "revision_vector": rev_vec.to_dict(),
                "validation_run_id": result.validation_run_id,
                "reason": result.reason,
                "derived_facts": list(result.derived_facts),
            }
            if result.claim_id:
                entry["claim_id"] = result.claim_id
            if result.affected_refs:
                entry["affected_refs"] = list(result.affected_refs)
            if reason is not None:
                entry["audit_reason"] = reason
            candidate.processed_commands[command_id] = entry

            # Append to event log (spec §6.10 — MUST include: event_id,
            # board_id, store_revision, command_id, actor, timestamp,
            # subject_ref, decision, rule/reason, input snapshot hash,
            # validation_run_id, affected_refs).
            subject_ref_val = ""
            affected_refs_val: list[str] = []
            input_snapshot_hash = previous_hash or ""
            if audit_context:
                subject_ref_val = str(audit_context.get("subject_ref") or "")
                affected = audit_context.get("affected_refs")
                if affected:
                    affected_refs_val = [str(r) for r in affected]
                # Issue #9: input_snapshot_hash is the GraphSnapshot hash the
                # validator read (supplied by the application service via
                # audit_context), NOT the previous Board payload hash.
                input_snapshot_hash = str(
                    audit_context.get("input_snapshot_hash") or input_snapshot_hash
                )
            if not affected_refs_val and result.affected_refs:
                affected_refs_val = list(result.affected_refs)
            rule_val = str((audit_context or {}).get("rule") or "")
            # Issue #9: an independent ``command_received`` event records
            # that the command was accepted for execution (spec §6.10 lists
            # it among the events every command must produce).  It carries
            # the same MUST fields as command_executed so the audit schema is
            # uniform.  It is distinct from ``command_executed`` (the outcome)
            # and from the ``processedCommands`` map (the idempotency receipt).
            candidate.events.append(
                {
                    "type": "command_received",
                    "event_id": f"E-{uuid.uuid4().hex[:16]}",
                    "board_id": board_id,
                    "command_id": command_id,
                    "decision": result.decision,
                    "actor": actor,
                    "timestamp": _now_iso(),
                    "store_revision": candidate.store_revision,
                    "subject_ref": subject_ref_val,
                    "affected_refs": affected_refs_val,
                    "input_snapshot_hash": input_snapshot_hash,
                    "validation_run_id": result.validation_run_id,
                    "rule": rule_val,
                    "request_hash": request_hash,
                    "reason": reason or "",
                }
            )
            event: dict[str, Any] = {
                "type": "command_executed",
                "event_id": f"E-{uuid.uuid4().hex[:16]}",
                "board_id": board_id,
                "command_id": command_id,
                "decision": result.decision,
                "actor": actor,
                "timestamp": _now_iso(),
                "store_revision": candidate.store_revision,
                "revision_vector": rev_vec.to_dict(),
                "input_snapshot_hash": input_snapshot_hash,
                "validation_run_id": result.validation_run_id,
                "subject_ref": subject_ref_val,
                "affected_refs": affected_refs_val,
                "rule": rule_val,
                "reason": result.reason or "",
            }
            candidate.events.append(event)

            # Issue #9: override / invalidation custom events appended by
            # domain handlers were stamped with the PRE-bump store_revision
            # (the candidate revision is only advanced above).  Patch every
            # command-scoped event to the authoritative post-bump revision
            # so the audit chain is internally consistent.
            for ev in candidate.events:
                if ev.get("command_id") == command_id and ev is not event:
                    ev["store_revision"] = candidate.store_revision

            # Re-hash after all mutations
            set_payload_hash(candidate, previous_hash=previous_hash)

            # Final schema/decode/invariant and serialization validation.
            candidate_data = candidate.to_dict()
            _validate_envelope_schema(candidate_data, board_id=board_id)
            if not _verify_payload_hash(candidate_data):
                raise ValueError("candidate payload hash does not verify")
            json.dumps(candidate_data, sort_keys=True, ensure_ascii=False)

            # Step 9: atomic write
            self._write_atomic(candidate)

            # Step 10: return result (with final revision vector)
            if result.committed:
                return CommandResult(
                    decision=result.decision,
                    command_id=command_id,
                    revision_vector=rev_vec,
                    validation_run_id=result.validation_run_id,
                    reason=result.reason,
                    derived_facts=result.derived_facts,
                    claim_id=result.claim_id,
                    affected_refs=result.affected_refs,
                )
            return result

    # ── internal: read + validate ─────────────────────────────────────

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        """Read and parse a JSON file.  Raises on I/O or parse error."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _read_valid_envelope(self, path: Path) -> BoardEnvelope:
        data = self._read_json_file(path)
        _validate_envelope_schema(data, board_id=self._board_id)
        if not _verify_payload_hash(data):
            raise ValueError(f"{path} payload hash mismatch")
        return BoardEnvelope.from_dict(data)

    def _migrate_primary_if_needed(self) -> None:
        try:
            raw = self._read_json_file(self._board_json)
        except (OSError, json.JSONDecodeError):
            return
        schema_version = raw.get("schemaVersion", 0)
        if not isinstance(schema_version, int):
            return
        if schema_version > CURRENT_SCHEMA_VERSION:
            raise BoardSchemaTooNewError(self._board_id, schema_version, CURRENT_SCHEMA_VERSION)
        if schema_version == CURRENT_SCHEMA_VERSION:
            return
        with self._lock:
            latest = self._read_json_file(self._board_json)
            latest_version = latest.get("schemaVersion", 0)
            if latest_version > CURRENT_SCHEMA_VERSION:
                raise BoardSchemaTooNewError(self._board_id, latest_version, CURRENT_SCHEMA_VERSION)
            if latest_version == CURRENT_SCHEMA_VERSION:
                return
            from .migrations import migrate_board_file

            migrate_board_file(
                self._board_json,
                expected_board_id=self._board_id,
                target_schema=CURRENT_SCHEMA_VERSION,
                failpoint=self._failpoint,
            )

    def _read_and_validate(self, path: Path) -> BoardEnvelope | None:
        try:
            return self._read_valid_envelope(path)
        except BoardSchemaTooNewError:
            raise
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _validate_primary_chain(self, primary: BoardEnvelope) -> None:
        if not self._board_json_bak.is_file():
            return
        try:
            backup_raw = self._read_json_file(self._board_json_bak)
        except (OSError, json.JSONDecodeError):
            # A valid primary is authoritative.  A damaged optional backup is
            # diagnostic material, not a reason to make healthy state
            # unavailable.
            return
        backup_schema = backup_raw.get("schemaVersion", 0)
        if isinstance(backup_schema, int) and backup_schema < CURRENT_SCHEMA_VERSION:
            # A schema migration backup is intentionally from the previous
            # schema and is not part of the v1 revision hash chain.
            return
        backup = self._read_and_validate(self._board_json_bak)
        if backup is None:
            return
        if primary.store_revision == backup.store_revision:
            # ``atomic_write_json`` rotates the current authoritative
            # primary into .bak before replacing it.  A crash at
            # after_backup_before_replace therefore leaves two identical,
            # complete copies of the old revision.  This is a valid
            # pre-commit state, not a rollback or a broken revision chain.
            if (
                primary.integrity.get("payloadHash") == backup.integrity.get("payloadHash")
                and primary.to_dict() == backup.to_dict()
            ):
                return
            raise BoardStoreCorruptError(
                "primary/backup have the same revision but different payloads"
            )
        if primary.store_revision < backup.store_revision:
            raise BoardStoreCorruptError(
                "primary revision is older than backup (possible rollback): "
                f"{primary.store_revision} vs {backup.store_revision}"
            )
        if primary.store_revision > backup.store_revision + 1:
            # Backup rotation is best-effort historical context.  A valid
            # lower non-adjacent revision is merely stale and cannot refute
            # the authoritative primary.
            return
        if primary.integrity.get("previousPayloadHash") != backup.integrity.get("payloadHash"):
            raise BoardStoreCorruptError("primary previousPayloadHash does not match backup")

    def _backup_revision_is_explainable(self, backup: BoardEnvelope) -> bool:
        try:
            raw = self._read_json_file(self._board_json)
        except (OSError, json.JSONDecodeError):
            return True
        raw_board = raw.get("board")
        if isinstance(raw_board, dict) and raw_board.get("board_id") not in (
            None,
            self._board_id,
        ):
            return False
        raw_revision = raw.get("storeRevision")
        if isinstance(raw_revision, int):
            if raw_revision != backup.store_revision + 1:
                return False
            raw_integrity = raw.get("integrity")
            if isinstance(raw_integrity, dict):
                previous = raw_integrity.get("previousPayloadHash")
                if previous is not None and previous != backup.integrity.get("payloadHash"):
                    return False
        return True

    def _quarantine_copy(self, path: Path, reason: str) -> Path | None:
        if not path.exists():
            return None
        try:
            self._quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = self._quarantine_dir / f"{path.name}.{time.time_ns()}.{reason}"
            shutil.copy2(path, target)
            return target
        except OSError:
            return None

    def _try_recover_from_backup(self) -> BoardEnvelope | None:
        with self._lock:
            try:
                primary = self._read_valid_envelope(self._board_json)
                self._validate_primary_chain(primary)
                return primary
            except BoardSchemaTooNewError:
                raise
            except (OSError, json.JSONDecodeError, ValueError, BoardStoreCorruptError):
                pass

            backup = self._read_and_validate(self._board_json_bak)
            if backup is None or not self._backup_revision_is_explainable(backup):
                return None

            recovered = backup.clone()
            recovered.store_revision = backup.store_revision + 1
            recovered.board["store_revision"] = recovered.store_revision
            recovered.events.append(
                {
                    "type": "store_recovered",
                    "actor": "json_store",
                    "reason": "primary invalid; restored from board.json.bak",
                    "recovered_from_store_revision": backup.store_revision,
                    "store_revision": recovered.store_revision,
                }
            )
            set_payload_hash(
                recovered,
                previous_hash=str(backup.integrity.get("payloadHash", "")),
            )
            recovered_data = recovered.to_dict()
            _validate_envelope_schema(recovered_data, board_id=self._board_id)
            self._quarantine_copy(self._board_json, "primary-corrupt")
            atomic_write_json(
                self._board_json,
                recovered_data,
                backup_path=None,
                fsync_dir=True,
                failpoint=self._failpoint,
                payload_hash_key="payloadHash",
            )
            warnings.warn(
                f"Recovered board {self._board_id!r} from board.json.bak; "
                "the invalid primary was quarantined",
                BoardRecoveryWarning,
                stacklevel=2,
            )
            return recovered

    def _load_locked(self) -> BoardEnvelope:
        try:
            primary = self._read_valid_envelope(self._board_json)
            self._validate_primary_chain(primary)
            return primary
        except BoardSchemaTooNewError:
            raise
        except (OSError, json.JSONDecodeError, ValueError, BoardStoreCorruptError) as exc:
            raise BoardStoreCorruptError(
                f"{self._board_json} is invalid for board {self._board_id!r}; "
                "mutations do not implicitly recover from backup"
            ) from exc

    def _write_atomic(self, envelope: BoardEnvelope) -> None:
        """Atomically write *envelope* to board.json with .bak rotation.

        Delegates to atomic_file.atomic_write_json.  Failpoint-injectable.
        """
        self._board_dir.mkdir(parents=True, exist_ok=True)
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

        data = envelope.to_dict()
        atomic_write_json(
            self._board_json,
            data,
            backup_path=self._board_json_bak,
            fsync_dir=True,
            failpoint=self._failpoint,
            payload_hash_key="integrity.payloadHash".split(".")[-1],
        )

    # ── initialization helper ─────────────────────────────────────────

    @classmethod
    def create_board(
        cls,
        board_dir: Path | str,
        *,
        board: Board,
        lock: Any,
        home: Path | None = None,
        failpoint: Any | None = None,
    ) -> "JsonBoardStore":
        """Create a new board on disk and return a JsonBoardStore for it.

        Writes the genesis envelope (store_revision=0, empty graphs,
        initial payload hash).  If the board already exists, raises
        FileExistsError.
        """
        board_dir = Path(board_dir)
        store = cls(
            board_dir,
            board_id=board.board_id,
            lock=lock,
            home=home,
            failpoint=failpoint,
        )
        store._assert_not_tombstoned()

        envelope = BoardEnvelope(
            store_format=STORE_FORMAT,
            schema_version=CURRENT_SCHEMA_VERSION,
            store_revision=0,
            board={
                "board_id": board.board_id,
                "project_uri": board.project_uri,
                "display_name": board.display_name,
                "schema_version": board.schema_version,
                "store_revision": 0,
                "created_at": board.created_at,
                "updated_at": board.updated_at,
                "policy": board.policy.to_dict(),
            },
            lifecycle={},
        )
        from .lifecycle import genesis_lifecycle

        envelope.lifecycle = genesis_lifecycle(
            scope=("session" if board.project_uri.startswith("session:") else "project"),
            created_at=board.created_at,
            origin_project_uri=board.project_uri,
        )
        # Genesis hash — no previous
        set_payload_hash(envelope, previous_hash=None)

        # First creation participates in the same serialization order as
        # every later mutation.
        with lock:
            # The first check above avoids needless directory creation; this
            # in-lock check closes the race with tombstone publication.
            store._assert_not_tombstoned()
            board_dir.mkdir(parents=True, exist_ok=True)
            if store._board_json.exists():
                raise FileExistsError(f"Board already exists: {store._board_json}")
            store._write_atomic(envelope)
        return store


# ── helpers ───────────────────────────────────────────────────────────


def _node_graph(node_dict: dict[str, Any]) -> str:
    """Extract graph id from a node dict via its ref string."""
    ref_str = str(node_dict.get("ref", ""))
    parts = ref_str.split(":", 2)
    if len(parts) >= 1:
        return parts[0]
    return ""


def _record_graph_ids(record: dict[str, Any]) -> set[str]:
    """Return every graph explicitly owned/touched by a domain record."""
    result: set[str] = set()
    graph = record.get("graph") or record.get("graph_id")
    if isinstance(graph, str) and graph:
        result.add(graph)
    for key in (
        "ref",
        "task_ref",
        "subject_ref",
        "subjectRef",
        "node_ref",
        "target_ref",
        "source_ref",
    ):
        value = record.get(key)
        if isinstance(value, str):
            result.add(_parse_ref(value, location=key).graph)
    affected = record.get("affected_refs", record.get("affectedRefs"))
    if affected is not None:
        if not isinstance(affected, list):
            raise ValueError("affected_refs must be a list")
        for value in affected:
            result.add(_parse_ref(value, location="affected_refs[]").graph)
    return result


def _graph_content(envelope: BoardEnvelope) -> dict[str, dict[str, Any]]:
    """Build an exact, revision-free content projection for each graph."""
    content: dict[str, dict[str, Any]] = {}
    for gid, graph in envelope.graphs.items():
        graph_data = copy.deepcopy(graph)
        graph_data.pop("revision", None)
        content[gid] = {
            "graph": graph_data,
            "nodes": {},
            "edges": {},
            "claims": {},
            "assertions": {},
            "evidence": {},
        }

    for record_id, record in envelope.nodes.items():
        gids = {_node_graph(record)}
        for gid in gids:
            if gid in content:
                content[gid]["nodes"][record_id] = copy.deepcopy(record)
    for collection_name in ("edges", "claims", "assertions", "evidence"):
        collection = getattr(envelope, collection_name)
        for record_id, record in collection.items():
            for gid in _record_graph_ids(record):
                if gid in content:
                    content[gid][collection_name][record_id] = copy.deepcopy(record)
    return content


def validate_board_envelope(
    envelope: BoardEnvelope | dict[str, Any],
    *,
    board_id: str | None = None,
    verify_hash: bool = True,
) -> None:
    """Public Phase-2 schema/decode/invariant oracle."""
    data = envelope.to_dict() if isinstance(envelope, BoardEnvelope) else envelope
    _validate_envelope_schema(data, board_id=board_id)
    if verify_hash and not _verify_payload_hash(data):
        raise AssertionError("payload hash does not match envelope content")
    BoardEnvelope.from_dict(data).build_graph_snapshot()


__all__ = [
    "BoardEnvelope",
    "BoardNotFoundError",
    "BoardRecoveryWarning",
    "BoardSchemaTooNewError",
    "BoardStoreCorruptError",
    "BoardTombstonedError",
    "CURRENT_SCHEMA_VERSION",
    "IdempotencyKeyReusedError",
    "JsonBoardStore",
    "STORE_FORMAT",
    "StaleRevisionError",
    "payload_hash",
    "set_payload_hash",
    "validate_board_envelope",
]
