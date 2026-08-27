"""Rebuildable Qdrant vector projection for crystal ledger heads.

The ledger is the source of truth. This module only owns derived state: it can be discarded
and rebuilt, only advances the watermark after Qdrant confirms a batch of data, and never lets
a projection failure roll back a successful ledger write.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import CrystalLedger
from clawcodex_ext.latent_memory.server.lib.solidification.models import (
    Revision,
    crystal_metadata_from_revision,
)

logger = logging.getLogger("memory-server.solidification")

_POINT_NAMESPACE = uuid.UUID("eff7b1ec-e2cc-4bce-850b-da3e93251d18")
_SEARCHABLE_STATUSES = ("candidate", "active", "canonical")
_SEARCH_VECTOR = "search"
_CLUSTER_VECTOR = "cluster"
_SEARCH_EMBEDDING_VERSION = 2
_CLUSTER_EMBEDDING_VERSION = 1


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def build_crystal_search_text(revision: Revision) -> str:
    """Build a positive retrieval representation for one ledger head.

    Negative applicability and known exceptions are deliberately excluded from the embedding.
    They are returned as payload metadata and applied as penalty terms during hierarchical fusion,
    so a query matching a does-not-apply condition does not make the crystal look *more* relevant.
    """

    asset = revision.asset if isinstance(revision.asset, dict) else {}
    applicability = asset.get("applicability")
    applicability = applicability if isinstance(applicability, dict) else {}
    applies_when = _string_values(applicability.get("applies_when") or asset.get("conditions"))

    claim = asset.get("claim")
    claim_values = _string_values(claim)
    sections: list[tuple[str, list[str]]] = [
        ("结论", claim_values or _string_values(revision.body)),
        ("主题", _string_values(revision.subject or asset.get("subject"))),
        ("谓词", _string_values(asset.get("predicate"))),
        ("对象", _string_values(asset.get("object"))),
        ("适用条件", applies_when),
        ("步骤", _string_values(asset.get("steps"))),
        ("关系", _string_values(asset.get("relations"))),
    ]
    for name, values in sorted((revision.facets or {}).items()):
        sections.append((f"特征-{name}", _string_values(values)))

    lines: list[str] = []
    seen: set[str] = set()
    for label, values in sections:
        unique = []
        for value in values:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        if unique:
            lines.append(f"{label}: {'; '.join(unique)}")
    return "\n".join(lines) or revision.body


def build_crystal_cluster_text(revision: Revision) -> str:
    """Return the stable, body-only representation used for crystallization."""
    return revision.body.strip()


def _applicability_payload(revision: Revision) -> dict[str, list[str]]:
    asset = revision.asset if isinstance(revision.asset, dict) else {}
    applicability = asset.get("applicability")
    applicability = applicability if isinstance(applicability, dict) else {}
    return {
        "applies_when": _string_values(
            applicability.get("applies_when") or asset.get("conditions")
        ),
        "does_not_apply_when": _string_values(applicability.get("does_not_apply_when")),
        "known_exceptions": _string_values(applicability.get("known_exceptions")),
    }


def qdrant_point_id(crystal_id: str) -> str:
    """Map any ledger crystal ID to a stable Qdrant-compatible UUID.

    Phase-one IDs use the human-readable ``cr_...`` form, which Qdrant cannot use as point IDs.
    UUIDv5 preserves stable upsert semantics without rewriting existing ledger identities.
    """
    return str(uuid.uuid5(_POINT_NAMESPACE, str(crystal_id)))


def _client_from_config(memory_config: dict[str, Any]) -> Any:
    from qdrant_client import QdrantClient

    vector_store = memory_config.get("vector_store", {}) or {}
    if vector_store.get("provider", "qdrant") != "qdrant":
        raise ValueError("solidification vector projection currently requires Qdrant")
    cfg = dict(vector_store.get("config", {}) or {})
    # Qdrant local mode only allows one client per storage path.
    # Keep this projection separate from mem0's own local client.
    if "path" in cfg and cfg["path"]:
        from pathlib import Path

        cfg["path"] = str(Path(cfg["path"]) / "solidification")
    kwargs: dict[str, Any] = {}
    for key in ("api_key", "url", "path", "host", "port", "prefer_grpc", "https"):
        value = cfg.get(key)
        if value is not None and value != "":
            kwargs[key] = value
    return QdrantClient(**kwargs)


def _field_condition(key: str, value: Any) -> Any:
    from qdrant_client.http import models

    if value == "*":
        return None
    if not isinstance(value, dict):
        if isinstance(value, list):
            return models.FieldCondition(key=key, match=models.MatchAny(any=value))
        return models.FieldCondition(key=key, match=models.MatchValue(value=value))
    if "eq" in value:
        return models.FieldCondition(key=key, match=models.MatchValue(value=value["eq"]))
    if "ne" in value:
        return models.FieldCondition(key=key, match=models.MatchExcept(**{"except": [value["ne"]]}))
    if "in" in value:
        return models.FieldCondition(key=key, match=models.MatchAny(any=value["in"]))
    if "nin" in value:
        return models.FieldCondition(key=key, match=models.MatchExcept(**{"except": value["nin"]}))
    range_keys = {key: value[key] for key in ("gt", "gte", "lt", "lte") if key in value}
    if range_keys and len(range_keys) == len(value):
        return models.FieldCondition(key=key, range=models.Range(**range_keys))
    raise ValueError(f"unsupported crystal projection filter for {key}: {value}")


def _build_filter(filters: dict[str, Any]) -> Any:
    from qdrant_client.http import models

    must: list[Any] = []
    should: list[Any] = []
    must_not: list[Any] = []
    for key, value in (filters or {}).items():
        normalized = {"$and": "AND", "$or": "OR", "$not": "NOT"}.get(key, key)
        if normalized in {"AND", "OR", "NOT"}:
            if not isinstance(value, list):
                raise ValueError(f"{normalized} filter must be a list")
            target = must if normalized == "AND" else should if normalized == "OR" else must_not
            target.extend(filter(None, (_build_filter(item) for item in value)))
            continue
        condition = _field_condition(normalized, value)
        if condition is not None:
            must.append(condition)
    if not (must or should or must_not):
        return None
    return models.Filter(
        must=must or None,
        should=should or None,
        must_not=must_not or None,
    )


class VectorProjection:
    """Incrementally project current ledger heads to a Qdrant collection."""

    def __init__(
        self,
        ledger: CrystalLedger,
        *,
        embed_fn: Callable[[list[str]], list[list[float]]],
        collection_name: str = "crystals",
        mode: str = "async",
        batch_size: int = 100,
        memory_config: dict[str, Any] | None = None,
        client: Any | None = None,
        vector_size: int | None = None,
        embedding_batch_size: int = 32,
    ) -> None:
        if mode not in {"async", "sync"}:
            raise ValueError("projection mode must be async or sync")
        self._ledger = ledger
        self._embed_fn = embed_fn
        self.collection_name = collection_name
        self.mode = mode
        self.batch_size = max(1, int(batch_size))
        self.embedding_batch_size = max(1, int(embedding_batch_size))
        self._owns_client = client is None
        self._client = client if client is not None else _client_from_config(memory_config or {})
        cfg = ((memory_config or {}).get("vector_store", {}) or {}).get("config", {}) or {}
        embed_cfg = ((memory_config or {}).get("embedder", {}) or {}).get("config", {}) or {}
        configured_size = (
            vector_size or cfg.get("embedding_model_dims") or embed_cfg.get("embedding_dims")
        )
        self._vector_size = int(configured_size) if configured_size else None
        self._flush_lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._batches = 0
        self._embedded = 0
        self._reused = 0
        self._search_reused = 0
        self._cluster_reused = 0
        self._deleted = 0
        self._payload_indexes_ensured = False

    @property
    def available(self) -> bool:
        return True

    def start(self) -> None:
        self._reset_incompatible_collection()
        if self.mode != "async" or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(
            target=self._worker,
            name="solidification-vector-projector",
            daemon=True,
        )
        self._thread.start()
        self._wake.set()  # resume any backlog left by a previous process

    def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        if self._owns_client and not (self._thread and self._thread.is_alive()):
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def notify(self, rev_id: int | None = None) -> None:
        if self.mode == "sync":
            try:
                self.flush()
            except Exception as exc:
                self._last_error = str(exc)
                raise
        else:
            self._wake.set()

    def _worker(self) -> None:
        try:
            while not self._stopping.is_set():
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                if self._stopping.is_set():
                    break
                try:
                    self.flush()
                except Exception as exc:  # retry on next notify/heartbeat
                    self._last_error = str(exc)
                    logger.error("vector projection batch failed: %s", exc, exc_info=True)
        finally:
            # CrystalLedger caches one SQLite connection per thread.
            self._ledger.close()

    def _collection_exists(self) -> bool:
        return bool(self._client.collection_exists(self.collection_name))

    def _reset_incompatible_collection(self) -> None:
        """Rebuild derived state when the collection is not the specified named-vector schema."""
        if not self._collection_exists():
            return
        info = self._client.get_collection(self.collection_name)
        config = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(config, "vectors", None)
        names = set(vectors) if isinstance(vectors, dict) else set()
        sizes = (
            {int(getattr(params, "size", 0)) for params in vectors.values()}
            if isinstance(vectors, dict)
            else set()
        )
        expected_names = {_SEARCH_VECTOR, _CLUSTER_VECTOR}
        size_mismatch = bool(self._vector_size is not None and sizes != {self._vector_size})
        if names == expected_names and not size_mismatch:
            return
        logger.warning(
            "rebuilding crystal projection with named vectors: found=%s sizes=%s",
            sorted(names),
            sorted(sizes),
        )
        self._ledger.set_projection_through("vector", 0)
        self._client.delete_collection(self.collection_name)
        self._payload_indexes_ensured = False

    def _ensure_collection(self, vector_size: int) -> None:
        from qdrant_client.http import models

        if not self._collection_exists():
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    name: models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                    for name in (_SEARCH_VECTOR, _CLUSTER_VECTOR)
                },
            )
            self._payload_indexes_ensured = False
        if self._payload_indexes_ensured:
            return
        for field in ("user_id", "agent_id", "run_id", "status", "asset_type"):
            try:
                self._client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            except Exception as exc:
                # Local/in-memory Qdrant may not implement payload indexes. Retrieval is still
                # correct; only production server performance is affected.
                logger.warning("cannot create payload index %s: %s", field, exc)
        self._payload_indexes_ensured = True

    @staticmethod
    def _payload(revision: Revision) -> dict[str, Any]:
        metadata = crystal_metadata_from_revision(revision)
        return {
            "data": revision.body,
            "hash": revision.content_hash,
            "created_at": revision.recorded_at,
            "search_text": build_crystal_search_text(revision),
            "search_embedding_version": _SEARCH_EMBEDDING_VERSION,
            "cluster_embedding_version": _CLUSTER_EMBEDDING_VERSION,
            "applicability": _applicability_payload(revision),
            **metadata,
        }

    def _project_page(self, revisions: list[Revision]) -> None:
        self._project_crystal_ids(
            list(dict.fromkeys(revision.crystal_id for revision in revisions))
        )

    def _embed_texts_in_batches(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for index in range(0, len(texts), self.embedding_batch_size):
            batch = texts[index : index + self.embedding_batch_size]
            embedded = self._embed_fn(batch)
            if len(embedded) != len(batch):
                raise RuntimeError(
                    f"embedder returned {len(embedded)} vectors for {len(batch)} texts"
                )
            for vector in embedded:
                if not vector:
                    raise RuntimeError("embedder returned an empty vector")
                result.append([float(value) for value in vector])
        return result

    def _project_crystal_ids(self, crystal_ids: list[str]) -> None:
        from qdrant_client.http import models

        crystal_ids = list(dict.fromkeys(str(value) for value in crystal_ids if value))
        if not crystal_ids:
            return
        heads = [self._ledger.head(crystal_id) for crystal_id in crystal_ids]
        live = [
            head
            for head in heads
            if head is not None and head.status in _SEARCHABLE_STATUSES and head.op != "dispute"
        ]
        dead_ids = [
            qdrant_point_id(crystal_id)
            for crystal_id, head in zip(crystal_ids, heads)
            if head is None or head.status not in _SEARCHABLE_STATUSES or head.op == "dispute"
        ]

        collection_exists = self._collection_exists()
        existing: dict[str, Any] = {}
        if live and collection_exists:
            records = self._client.retrieve(
                collection_name=self.collection_name,
                ids=[qdrant_point_id(head.crystal_id) for head in live],
                with_payload=True,
                with_vectors=True,
            )
            for record in records:
                payload = dict(getattr(record, "payload", None) or {})
                crystal_id = str(payload.get("crystal_id") or "")
                if crystal_id:
                    existing[crystal_id] = record

        needs_search: list[Revision] = []
        needs_cluster: list[Revision] = []
        vectors: dict[str, dict[str, list[float]]] = {}
        for head in live:
            old = existing.get(head.crystal_id)
            old_payload = dict(getattr(old, "payload", None) or {}) if old else {}
            old_vectors = getattr(old, "vector", None) if old else None
            old_vectors = old_vectors if isinstance(old_vectors, dict) else {}
            same_content = old_payload.get("content_hash") == head.content_hash
            search_vector = old_vectors.get(_SEARCH_VECTOR)
            cluster_vector = old_vectors.get(_CLUSTER_VECTOR)
            reuse_search = bool(
                same_content
                and old_payload.get("search_embedding_version") == _SEARCH_EMBEDDING_VERSION
                and isinstance(search_vector, (list, tuple))
                and search_vector
            )
            reuse_cluster = bool(
                same_content
                and old_payload.get("cluster_embedding_version") == _CLUSTER_EMBEDDING_VERSION
                and isinstance(cluster_vector, (list, tuple))
                and cluster_vector
            )
            vectors[head.crystal_id] = {}
            if reuse_search:
                vectors[head.crystal_id][_SEARCH_VECTOR] = [float(value) for value in search_vector]
                self._search_reused += 1
            else:
                needs_search.append(head)
            if reuse_cluster:
                vectors[head.crystal_id][_CLUSTER_VECTOR] = [
                    float(value) for value in cluster_vector
                ]
                self._cluster_reused += 1
            else:
                needs_cluster.append(head)
            if reuse_search and reuse_cluster:
                self._reused += 1

        if needs_search:
            embedded = self._embed_texts_in_batches(
                [build_crystal_search_text(head) for head in needs_search]
            )
            for head, vector in zip(needs_search, embedded):
                vectors[head.crystal_id][_SEARCH_VECTOR] = vector
        if needs_cluster:
            embedded = self._embed_texts_in_batches(
                [build_crystal_cluster_text(head) for head in needs_cluster]
            )
            for head, vector in zip(needs_cluster, embedded):
                vectors[head.crystal_id][_CLUSTER_VECTOR] = vector
        self._embedded += len(needs_search) + len(needs_cluster)

        if live:
            dimensions = {
                len(vector) for head in live for vector in vectors[head.crystal_id].values()
            }
            if len(dimensions) != 1:
                raise RuntimeError(
                    f"inconsistent crystal embedding dimensions: {sorted(dimensions)}"
                )
            first_size = next(iter(dimensions))
            if self._vector_size is not None and first_size != self._vector_size:
                raise RuntimeError(
                    f"embedding dimension {first_size} != configured {self._vector_size}"
                )
            self._vector_size = self._vector_size or first_size
            self._ensure_collection(self._vector_size)
            points = [
                models.PointStruct(
                    id=qdrant_point_id(head.crystal_id),
                    vector=vectors[head.crystal_id],
                    payload=self._payload(head),
                )
                for head in live
            ]
            self._client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )

        if dead_ids and self._collection_exists():
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=dead_ids,
                wait=True,
            )
            self._deleted += len(dead_ids)

    def reconcile_crystals(self, crystal_ids: list[str]) -> int:
        """Sync the selected heads even when no new revisions were appended.

        A rollback only changes ``crystal_head``, so it cannot be discovered through the normal
        revision watermark. This targeted path restores or deletes the affected points immediately
        without rolling that watermark back.
        """
        unique_ids = list(dict.fromkeys(str(value) for value in crystal_ids if value))
        with self._flush_lock:
            self._project_crystal_ids(unique_ids)
            self._last_error = None
        return len(unique_ids)

    def cluster_vectors_for(self, content_hashes: dict[str, str]) -> dict[str, list[float]]:
        """Return body-only cluster vectors matching the current ledger heads.

        The content-hash check is essential because the async projection may lag the authoritative
        ledger. Missing or stale points are simply omitted; callers can safely fall back to
        embedding only the missing entries.
        """
        if not content_hashes or not self._collection_exists():
            return {}
        crystal_ids = list(content_hashes)
        records: list[Any] = []
        for index in range(0, len(crystal_ids), 256):
            records.extend(
                self._client.retrieve(
                    collection_name=self.collection_name,
                    ids=[
                        qdrant_point_id(crystal_id)
                        for crystal_id in crystal_ids[index : index + 256]
                    ],
                    with_payload=True,
                    with_vectors=[_CLUSTER_VECTOR],
                )
            )
        result: dict[str, list[float]] = {}
        for record in records:
            payload = dict(getattr(record, "payload", None) or {})
            crystal_id = str(payload.get("crystal_id") or "")
            named_vectors = getattr(record, "vector", None)
            named_vectors = named_vectors if isinstance(named_vectors, dict) else {}
            vector = named_vectors.get(_CLUSTER_VECTOR)
            if (
                crystal_id in content_hashes
                and payload.get("content_hash") == content_hashes[crystal_id]
                and payload.get("cluster_embedding_version") == _CLUSTER_EMBEDDING_VERSION
                and isinstance(vector, (list, tuple))
            ):
                result[crystal_id] = [float(value) for value in vector]
        return result

    def flush(self) -> int:
        """Project all pending revisions and return the resulting watermark."""
        with self._flush_lock:
            state = self._ledger.projection_state().get("vector", {})
            through = int(state.get("through_rev", 0))
            while True:
                page = self._ledger.revisions_after(through, limit=self.batch_size)
                if not page:
                    break
                self._project_page(page)
                through = page[-1].rev_id
                # The watermark is committed only after all Qdrant writes above complete.
                self._ledger.set_projection_through("vector", through)
                self._batches += 1
            self._last_error = None
            return through

    def search(
        self,
        query: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> dict[str, list[dict[str, Any]]]:
        if not self._collection_exists():
            return {"results": []}
        combined = dict(filters or {})
        if combined.get("layer") == "crystallized":
            combined.pop("layer", None)
        for key, value in (
            ("user_id", user_id),
            ("agent_id", agent_id),
            ("run_id", run_id),
        ):
            if value:
                combined[key] = value
        combined.setdefault("status", {"in": list(_SEARCHABLE_STATUSES)})
        vectors = self._embed_fn([query])
        if len(vectors) != 1 or not vectors[0]:
            raise RuntimeError("query embedder returned no vector")
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=[float(value) for value in vectors[0]],
            using=_SEARCH_VECTOR,
            query_filter=_build_filter(combined),
            limit=max(1, int(limit)),
            with_payload=True,
            with_vectors=False,
        )
        results: list[dict[str, Any]] = []
        promoted = ("user_id", "agent_id", "run_id", "actor_id", "role")
        core = {"data", "hash", "created_at", "updated_at", *promoted}
        for point in response.points:
            payload = dict(point.payload or {})
            item: dict[str, Any] = {
                "id": str(payload.get("crystal_id") or point.id),
                "memory": payload.get("data", ""),
                "hash": payload.get("hash"),
                "created_at": payload.get("created_at"),
                "score": float(point.score),
            }
            for key in promoted:
                if key in payload:
                    item[key] = payload[key]
            metadata = {key: value for key, value in payload.items() if key not in core}
            if metadata:
                item["metadata"] = metadata
            results.append(item)
        return {"results": results}

    def rebuild(self) -> dict[str, int]:
        with self._flush_lock:
            self._ledger.set_projection_through("vector", 0)
            if self._collection_exists():
                self._client.delete_collection(self.collection_name)
                self._payload_indexes_ensured = False
        through = self.flush()
        return {
            "through_rev": through,
            "search_embedding_version": _SEARCH_EMBEDDING_VERSION,
            "cluster_embedding_version": _CLUSTER_EMBEDDING_VERSION,
        }

    def reset(self) -> None:
        with self._flush_lock:
            if self._collection_exists():
                self._client.delete_collection(self.collection_name)
                self._payload_indexes_ensured = False

    def reset_with_ledger(self) -> dict[str, Any]:
        """Atomically exclude projector work while the projection and ledger are cleared."""
        with self._flush_lock:
            if self._collection_exists():
                self._client.delete_collection(self.collection_name)
                self._payload_indexes_ensured = False
            return self._ledger.reset()

    def state(self) -> dict[str, Any]:
        watermark = self._ledger.projection_state().get("vector", {}).get("through_rev", 0)
        try:
            collection_exists = self._collection_exists()
        except Exception as exc:
            collection_exists = False
            self._last_error = str(exc)
        return {
            "enabled": True,
            "mode": self.mode,
            "collection": self.collection_name,
            "collection_exists": collection_exists,
            "vector_names": [_SEARCH_VECTOR, _CLUSTER_VECTOR],
            "search_embedding_version": _SEARCH_EMBEDDING_VERSION,
            "cluster_embedding_version": _CLUSTER_EMBEDDING_VERSION,
            "searchable_statuses": list(_SEARCHABLE_STATUSES),
            "excluded_ops": ["dispute"],
            "through_rev": int(watermark),
            "lag": max(0, self._ledger.max_rev_id() - int(watermark)),
            "last_error": self._last_error,
            "batches": self._batches,
            "embedded": self._embedded,
            "vectors_reused": self._reused,
            "search_vectors_reused": self._search_reused,
            "cluster_vectors_reused": self._cluster_reused,
            "deleted": self._deleted,
        }
