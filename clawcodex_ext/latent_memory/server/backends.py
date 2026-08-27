from __future__ import annotations

import inspect
import logging
import os
import uuid
from typing import Any, Protocol

from clawcodex_ext.latent_memory.server.config import register_custom_providers
from clawcodex_ext.latent_memory.server.schemas import AddRequest, SearchRequest

logger = logging.getLogger("memory-server")

# Dedup scope level: controls the narrowest ID range used for mem0 add() dedup retrieval.
# "user"  -> dedup by user_id only (agent_id/run_id sink into metadata, dedup across sessions)
# "agent" -> dedup by user_id + agent_id (only run_id sinks)
# "run"   -> dedup by all 3 IDs (original behavior, dedup within a session)
DEDUP_SCOPE: str = os.getenv("DEDUP_SCOPE", "user").lower().strip()


class MemoryBackend(Protocol):
    """Memory backend protocol -- defines the interface every backend must implement.

    Any class implementing this protocol can be injected via MemoryService(backend=xxx) to swap the
    underlying storage implementation (e.g. from mem0 to pure Qdrant or Chroma) without changing the
    transport or business layers.
    """

    @property
    def ready(self) -> bool:
        """Whether the backend has finished initializing."""
        ...

    def start(self) -> None:
        """Initialize backend resources."""
        ...

    def stop(self) -> None:
        """Release backend resources."""
        ...

    def add_memories(self, request: AddRequest) -> Any: ...

    def search_memories(self, request: SearchRequest) -> Any: ...

    def get_memories(self, filters: dict[str, Any]) -> Any: ...

    def get_memory(self, memory_id: str) -> Any: ...

    def get_memories_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Read memories in batch by ID, while remaining backend-agnostic."""
        ...

    def get_memories_with_vectors_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Read memories in batch along with their stored vectors, for internal processing."""
        ...

    def update_memory(self, memory_id: str, data: str) -> Any: ...

    def delete_memory(self, memory_id: str) -> None: ...

    def delete_all_memories(self, filters: dict[str, Any]) -> None: ...

    def memory_history(self, memory_id: str) -> Any: ...

    def reset_all(self) -> None: ...

    def health(self) -> dict[str, str]: ...


def supports_kwarg(func: Any, name: str) -> bool:
    """Determine whether the given function accepts a named keyword arg (including **kwargs).

    Used to adapt to different mem0 SDK versions: some do not support parameters such as timestamp;
    this function detects at runtime how to pass arguments.
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
    )


def add_metadata_fallback(params: dict[str, Any], key: str, value: Any) -> None:
    """When the mem0 SDK does not support a top-level parameter, degrade it into the metadata dict.

    Keeps data loss-free while remaining compatible with older SDK versions.
    """
    metadata = dict(params.get("metadata") or {})
    metadata.setdefault(key, value)
    params["metadata"] = metadata


def set_search_limit_param(params: dict[str, Any], search_func: Any, limit: int) -> None:
    """Set the search result count parameter for both mem0 1.x and 2.x SDKs."""
    if supports_kwarg(search_func, "top_k"):
        params["top_k"] = limit
    else:
        params["limit"] = limit


def build_scope_filters(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    base_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge user_id / agent_id / run_id into a filter dict.

    Keys in base_filters are preserved; scope params are only appended when non-empty.
    An empty dict is returned when no scope is specified (some operations disallow this case).
    """
    filters: dict[str, Any] = {}
    if base_filters:
        filters.update(base_filters)
    if user_id:
        filters["user_id"] = user_id
    if agent_id:
        filters["agent_id"] = agent_id
    if run_id:
        filters["run_id"] = run_id
    return filters


class Mem0MemoryBackend:
    """Default memory backend based on the mem0ai SDK.

    Wraps Memory.from_config() initialization and all CRUD operations, while handling cross-version
    SDK parameter compatibility (timestamp / observation_date).
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._memory: Any | None = None

    @property
    def ready(self) -> bool:
        """Whether the mem0 instance has been initialized via start()."""
        return self._memory is not None

    def start(self) -> None:
        """Register custom embedders and initialize the mem0 instance."""
        register_custom_providers()
        from mem0 import Memory

        logger.info("正在初始化 Mem0...")
        self._memory = Memory.from_config(self.config)
        logger.info(
            "Mem0 就绪: llm=%s, embedder=%s, vector_store=%s",
            self.config.get("llm", {}).get("provider", "?"),
            self.config.get("embedder", {}).get("provider", "?"),
            self.config.get("vector_store", {}).get("provider", "?"),
        )

    def stop(self) -> None:
        """Release the mem0 instance reference."""
        logger.info("关闭 Mem0 后端")
        self._memory = None

    def memory(self) -> Any:
        """Return the initialized mem0 instance, raising RuntimeError if not ready."""
        if self._memory is None:
            raise RuntimeError("记忆尚未初始化")
        return self._memory

    def add_memories(self, request: AddRequest) -> Any:
        """Write conversation messages to mem0 and trigger memory extraction.

        Dynamically detects SDK-unsupported params (timestamp / observation_date); when unsupported,
        they are degraded into metadata so data is never lost.

        Dedup scope degradation: based on the DEDUP_SCOPE config, only the IDs at the corresponding
        level are passed as mem0 top-level params (participating in the Phase-1 dedup retrieval
        filter); narrower IDs sink into metadata (kept queryable in storage, but not in the dedup
        filter).
        """
        memory = self.memory()
        params: dict[str, Any] = {}

        # ── Dedup scope degradation ──
        demoted_ids: dict[str, str] = {}
        if DEDUP_SCOPE == "user":
            # Only user_id participates in dedup; agent_id / run_id sink
            if request.user_id:
                params["user_id"] = request.user_id
                if request.agent_id:
                    demoted_ids["agent_id"] = request.agent_id
                if request.run_id:
                    demoted_ids["run_id"] = request.run_id
            elif request.agent_id:
                params["agent_id"] = request.agent_id
                if request.run_id:
                    demoted_ids["run_id"] = request.run_id
            elif request.run_id:
                params["run_id"] = request.run_id
        elif DEDUP_SCOPE == "agent":
            # user_id + agent_id participate in dedup; only run_id sinks
            if request.user_id:
                params["user_id"] = request.user_id
            if request.agent_id:
                params["agent_id"] = request.agent_id
            if request.run_id:
                if request.user_id or request.agent_id:
                    demoted_ids["run_id"] = request.run_id
                else:
                    params["run_id"] = request.run_id
        else:
            # "run" or invalid value -> original behavior, all IDs participate in dedup
            if request.user_id:
                params["user_id"] = request.user_id
            if request.agent_id:
                params["agent_id"] = request.agent_id
            if request.run_id:
                params["run_id"] = request.run_id

        # Merge metadata: original metadata + demoted IDs
        merged_metadata = dict(request.metadata or {})
        if demoted_ids:
            merged_metadata.update(demoted_ids)
        if merged_metadata:
            params["metadata"] = merged_metadata

        if request.custom_instructions:
            params["prompt"] = request.custom_instructions
        if request.timestamp is not None:
            if supports_kwarg(memory.add, "timestamp"):
                params["timestamp"] = request.timestamp
            else:
                add_metadata_fallback(params, "timestamp", request.timestamp)
        if request.observation_date:
            if supports_kwarg(memory.add, "observation_date"):
                params["observation_date"] = request.observation_date
            else:
                add_metadata_fallback(params, "observation_date", request.observation_date)

        return memory.add(request.messages, **params)

    def search_memories(self, request: SearchRequest) -> Any:
        """Retrieve memories by semantic similarity, auto-merging scope and custom filters."""
        memory = self.memory()
        filters = build_scope_filters(
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            base_filters=request.filters,
        )
        params: dict[str, Any] = {}
        set_search_limit_param(params, memory.search, request.limit)
        if filters:
            params["filters"] = filters
        if request.rerank:
            params["rerank"] = True

        return memory.search(request.query, **params)

    def get_memories(self, filters: dict[str, Any]) -> Any:
        memory = self.memory()
        # mem0 2.0.4's get_all controls the return count via top_k, default 20
        # Explicitly pass a large top_k to avoid truncation when listing the crystal library composition
        # Does not affect search's limit (search goes through a separate path)
        if supports_kwarg(memory.get_all, "top_k"):
            return memory.get_all(filters=filters, top_k=10000)
        return memory.get_all(filters=filters)

    def get_memory(self, memory_id: str) -> Any:
        return self.memory().get(memory_id)

    @staticmethod
    def _record_to_memory_item(record: Any, *, include_vector: bool = False) -> dict[str, Any]:
        """Convert a vector-store record into the public mem0 ``get`` structure."""
        payload = dict(getattr(record, "payload", None) or {})
        promoted = ("user_id", "agent_id", "run_id", "actor_id", "role")
        core = {
            "data",
            "hash",
            "created_at",
            "updated_at",
            "id",
            "text_lemmatized",
            "attributed_to",
            *promoted,
        }
        item: dict[str, Any] = {
            "id": str(getattr(record, "id", "")),
            "memory": payload.get("data", ""),
            "hash": payload.get("hash"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }
        for key in promoted:
            if key in payload:
                item[key] = payload[key]
        metadata = {key: value for key, value in payload.items() if key not in core}
        if metadata:
            item["metadata"] = metadata
        if include_vector:
            vector = getattr(record, "vector", None)
            if isinstance(vector, dict):
                vector = next(iter(vector.values()), None)
            if isinstance(vector, (list, tuple)):
                item["embedding"] = list(vector)
        return item

    def _retrieve_memories_by_ids(
        self, memory_ids: list[str], *, with_vectors: bool
    ) -> list[dict[str, Any]]:
        """Batch-retrieve multiple mem0 points directly through its Qdrant adapter.

        Qdrant does not guarantee result order, so the caller must correlate by ID. Keeping this
        operation inside our own backend adapter avoids modifying mem0 itself.
        """
        ids = list(dict.fromkeys(str(memory_id) for memory_id in memory_ids if memory_id))
        if not ids:
            return []
        vector_store = self.memory().vector_store
        client = getattr(vector_store, "client", None)
        collection_name = getattr(vector_store, "collection_name", None)
        if client is None or not collection_name:
            raise RuntimeError("Mem0MemoryBackend requires a Qdrant vector store")
        qdrant_ids: list[int | str] = []
        for memory_id in ids:
            try:
                qdrant_ids.append(str(uuid.UUID(memory_id)))
            except (ValueError, AttributeError):
                if memory_id.isdigit():
                    qdrant_ids.append(int(memory_id))
                else:
                    logger.warning("批量读取: 跳过非法 Qdrant point ID %r", memory_id)
        if not qdrant_ids:
            return []
        records: list[Any] = []
        for index in range(0, len(qdrant_ids), 256):
            records.extend(
                client.retrieve(
                    collection_name=collection_name,
                    ids=qdrant_ids[index : index + 256],
                    with_payload=True,
                    with_vectors=with_vectors,
                )
            )
        return [
            self._record_to_memory_item(record, include_vector=with_vectors) for record in records
        ]

    def get_memories_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-read raw memories, without returning their possibly-large vectors."""
        return self._retrieve_memories_by_ids(memory_ids, with_vectors=False)

    def get_memories_with_vectors_by_ids(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Batch-read raw memories, returning the vectors mem0 already stored along with them."""
        return self._retrieve_memories_by_ids(memory_ids, with_vectors=True)

    def update_memory(self, memory_id: str, data: str) -> Any:
        return self.memory().update(memory_id, data=data)

    def delete_memory(self, memory_id: str) -> None:
        self.memory().delete(memory_id)

    def delete_all_memories(self, filters: dict[str, Any]) -> None:
        memory = self.memory()
        if supports_kwarg(memory.delete_all, "filters"):
            memory.delete_all(filters=filters)
        else:
            # Older mem0 does not support the filters param; fetch first, then delete one by one
            result = memory.get_all(filters=filters)
            memories = result.get("results", []) if isinstance(result, dict) else []
            for m in memories:
                memory_id = m.get("id")
                if memory_id:
                    memory.delete(memory_id)
            logger.info("delete_all: 逐个删除 %d 条记忆 (filters=%s)", len(memories), filters)

    def memory_history(self, memory_id: str) -> Any:
        return self.memory().history(memory_id)

    def reset_all(self) -> None:
        self.memory().reset()

    def health(self) -> dict[str, str]:
        """Return the backend health status and a config summary."""
        return {
            "status": "ok",
            "llm": self.config.get("llm", {}).get("provider", "?"),
            "embedder": self.config.get("embedder", {}).get("provider", "?"),
        }
