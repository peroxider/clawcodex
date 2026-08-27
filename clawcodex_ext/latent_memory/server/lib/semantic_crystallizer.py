"""Semantic crystallization orchestration.

The Prompt, client, state, model, clustering and retention helper functions
reside in clawcodex_ext.latent_memory.server.lib.crystallization.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.crystallization.clients import (
    build_embed_fn_from_config as build_embed_fn_from_config,
    embed_batch as embed_batch,
    embed_batch_openai as embed_batch_openai,
    llm_call as llm_call,
    llm_call_ollama as llm_call_ollama,
    llm_call_openai as llm_call_openai,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.cluster import (
    avg_similarity,
    cluster_similarity_graph,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.models import (
    _clip_text,
    _display_text,
    _flatten_facets,
    _normalize_facets,
    aggregate_crystal_composition,
    asset_type_for_memory,
    asset_types_absorb_compatible,
    normalize_merged_crystal,
    subject_key_for_memory,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.prompts import (
    FACET_KEYS,
    MERGE_JSON_SCHEMA,
    MERGE_SYSTEM_PROMPT,
    MERGE_USER_TEMPLATE,
    detect_dominant_language,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.quality import ClusterQualityFilter
from clawcodex_ext.latent_memory.server.lib.crystallization.retention import (
    judge_retention,
    validate_or_repair_retention,
    validate_retention_judge,
)
from clawcodex_ext.latent_memory.server.lib.crystallization.stats import LLMStatsTracker
from clawcodex_ext.latent_memory.server.lib.crystallization.store import (
    CrystallizationState,
    _load_state,
    _save_state,
    _write_audit_record,
    finalize_crystallization_state,
)
from clawcodex_ext.latent_memory.server.lib.solidification.bridge import build_bridge

logger = logging.getLogger("memory-server.crystallizer")


def _evidence_run_ids(facts: list[dict[str, Any]]) -> list[str]:
    """Collect the sessions that contributed these facts to the current merge event."""
    run_ids: list[str] = []
    for fact in facts:
        metadata = fact.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        value = fact.get("run_id") or metadata.get("run_id")
        text = str(value or "").strip()
        if text and text not in run_ids:
            run_ids.append(text)
    return run_ids


class SemanticCrystallizer:
    """Semantic crystallizer.

    Dependencies are injected via callables, without coupling to a concrete backend implementation:
      - backend_accessor: () → MemoryBackend-like instance
      - embed_fn: (texts) → embeddings
      - llm_fn: (system, user, schema) → parsed JSON dict
    """

    def __init__(
        self,
        backend_accessor: Callable[[], Any],
        embed_fn: Callable[[list[str]], list[list[float]]],
        llm_fn: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        config: dict[str, Any],
        solidification: Any | None = None,
    ):
        self._backend_accessor = backend_accessor
        self._embed_fn = embed_fn
        # Every crystallization operation goes through the authoritative ledger bridge layer (fail-closed).
        self._solidification = solidification
        self._ledger = build_bridge(solidification)
        # Wrap llm_fn to count the number of calls and token usage.
        # Token is only captured under the openai provider; the ollama path is not counted.
        self._llm_stats = LLMStatsTracker()
        self._llm_fn = self._llm_stats.wrap(llm_fn)
        self._threshold: int = config.get("threshold", 50)
        self._interval_seconds: float = config.get("interval_hours", 24) * 3600
        self._min_cluster_size: int = config.get("min_cluster_size", 3)
        self._cluster_create_similarity: float = config.get("cluster_create_similarity", 0.60)
        self._cluster_absorb_similarity: float = config.get("cluster_absorb_similarity", 0.52)
        self._cluster_min_avg_similarity: float = config.get("cluster_min_avg_similarity", 0.50)
        self._cluster_max_size: int = max(1, config.get("cluster_max_size", 12))
        self._max_clusters_per_run: int = max(1, config.get("max_clusters_per_run", 10))
        self._failure_backoff_seconds: int = max(0, config.get("failure_backoff_minutes", 15) * 60)
        self._max_fact_attempts: int = max(1, int(config.get("max_fact_attempts", 3)))
        self._max_fact_chars: int = max(0, config.get("max_fact_chars", 1200))
        self._max_crystal_chars: int = max(0, config.get("max_crystal_chars", 2000))
        self._max_display_chars: int = max(120, config.get("max_display_chars", 420))
        self._embedding_batch_size: int = max(1, int(config.get("embedding_batch_size", 32)))
        self._quality_filter = ClusterQualityFilter(
            self._llm_fn,
            enabled=bool(config.get("quality_filter_enabled", True)),
            max_fact_chars=self._max_fact_chars,
            max_crystal_chars=self._max_crystal_chars,
            min_crystal_confidence=float(config.get("min_crystal_confidence", 0.65)),
        )
        self._schema_version: int = int(config.get("schema_version", 2))
        self._max_source_ids_per_crystal: int = max(
            1, int(config.get("max_source_ids_per_crystal", 48))
        )
        self._subject_split_enabled: bool = bool(config.get("subject_split_enabled", True))
        self._state_path: str = config.get("state_path", "local_mem0/crystallize_state.json")
        self._audit_path: str = config.get("audit_path", "local_mem0/crystallize_audit.jsonl")
        self._audit_max_bytes: int = max(0, config.get("audit_max_bytes", 10 * 1024 * 1024))
        self._audit_backups: int = max(1, config.get("audit_backups", 3))
        self._last_cluster_diagnostics: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._state = _load_state(self._state_path)
        total_pending = sum(len(v) for v in self._state.pending_ids.values())
        logger.info(
            "结晶器初始化: threshold=%d, interval=%dh, min_cluster=%d, create_sim=%.2f, absorb_sim=%.2f, max_cluster=%d, users=%d, pending=%d",
            self._threshold,
            config.get("interval_hours", 24),
            self._min_cluster_size,
            self._cluster_create_similarity,
            self._cluster_absorb_similarity,
            self._cluster_max_size,
            len(self._state.pending_ids),
            total_pending,
        )

    @property
    def state(self) -> CrystallizationState:
        return self._state

    @property
    def solidification(self) -> Any | None:
        """The solidification layer facade, or None when disabled."""
        return self._solidification

    def stats(self) -> dict[str, Any]:
        """Return the crystallizer's cumulative statistics snapshot (thread-safe read)."""
        return self._llm_stats.snapshot()

    def reset_stats(self) -> dict[str, Any]:
        """Reset the statistics counters and return the snapshot before reset."""
        return self._llm_stats.reset()

    def get_composition(self, user_id: str) -> dict[str, Any]:
        """Return a snapshot of the composition of the specified user's current crystallized knowledge base.

        Used in tests to intuitively view the distribution of various crystal types such as
        skill_card / rule_card, their version evolution, and average confidence.
        Read-only on the backend; does not modify state or call the LLM.
        """
        try:
            crystals = self._ledger.current_crystals(user_id=user_id)
        except Exception as exc:
            logger.warning("结晶器: 拉取结晶库构成失败: %s", exc)
            return {
                "user_id": user_id,
                "total": 0,
                "by_asset_type": {},
                "by_knowledge_type": {},
                "avg_confidence": 0.0,
                "unique_source_ids": 0,
                "version_distribution": {},
                "error": str(exc),
            }

        return aggregate_crystal_composition(crystals, user_ids=[user_id])

    def get_composition_aggregated(self, user_ids: list[str]) -> dict[str, Any]:
        """Aggregate the crystallized knowledge base composition of multiple users (benchmark scenario: one user_id per dialogue/question).

        Returns the same structure as get_composition, but fields such as total /
        by_asset_type are summed across all users, and avg_confidence is a
        cross-user weighted average.
        """
        all_crystals: list[dict[str, Any]] = []
        for uid in user_ids:
            try:
                all_crystals.extend(self._ledger.current_crystals(user_id=uid))
            except Exception as exc:
                logger.warning("结晶器: 拉取用户 %s 结晶构成失败: %s", uid, exc)
                continue
        return aggregate_crystal_composition(all_crystals, user_ids=user_ids)

    def clear_user_state(self, user_id: str) -> int:
        """Clear the crystallizer state for the specified user and return the number of pending items removed."""
        with self._lock:
            pending_ids = self._state.pending_ids.get(user_id, [])
            pending_count = len(pending_ids)
            for fact_id in pending_ids:
                self._state.fact_attempts.pop(fact_id, None)
            self._state.pending_ids.pop(user_id, None)
            self._state.last_run.pop(user_id, None)
            self._state.last_check.pop(user_id, None)
            self._state.last_check_passed.pop(user_id, None)
            self._state.last_failed_attempt.pop(user_id, None)
            self._save_state_locked()
            return pending_count

    def reset_all_state(self) -> dict[str, Any]:
        """Completely reset the crystallizer state: clear in-memory state + delete the state file + delete audit logs (including rotated backups).

        Returns a statistics summary before the reset. Used for a factory-level full clear.
        """
        with self._lock:
            summary = {
                "pending_count": sum(len(v) for v in self._state.pending_ids.values()),
                "total_created": self._state.total_created,
                "total_absorbed": self._state.total_absorbed,
                "total_failed": self._state.total_failed,
                "total_rejected": self._state.total_rejected,
                "total_evicted": self._state.total_evicted,
            }
            # Reset the in-memory state to its default value
            self._state = CrystallizationState()
            self._save_state_locked()

        # Delete audit log files (including rotated backups .jsonl.1, .jsonl.2, ...)
        audit_p = Path(self._audit_path)
        deleted_files: list[str] = []
        if audit_p.exists():
            audit_p.unlink()
            deleted_files.append(audit_p.name)
        idx = 1
        while True:
            rotated = audit_p.with_suffix(audit_p.suffix + f".{idx}")
            if not rotated.exists():
                break
            rotated.unlink()
            deleted_files.append(rotated.name)
            idx += 1

        logger.info(
            "结晶器: 全量重置完成, 清除 pending=%d, created=%d, absorbed=%d, 删除审计文件=%s",
            summary["pending_count"],
            summary["total_created"],
            summary["total_absorbed"],
            deleted_files or "无",
        )
        return summary

    def notify_new_facts(self, user_id: str, fact_ids: list[str]) -> None:
        """Called after add_memories returns. Accumulates the user's pending_ids and checks whether crystallization should be triggered."""
        if not fact_ids:
            return
        with self._lock:
            existing = set(self._state.pending_ids.get(user_id, []))
            new_ids = [fid for fid in fact_ids if fid not in existing]
            if new_ids:
                self._state.pending_ids.setdefault(user_id, []).extend(new_ids)
                self._save_state_locked()
            user_count = len(self._state.pending_ids.get(user_id, []))
        logger.info(
            "结晶器: 新增 %d 条事实 (去重后 %d), 累计待结晶 %d 条 (user=%s)",
            len(fact_ids),
            len(new_ids),
            user_count,
            user_id,
        )
        self._check_gates(user_id)

    def force_crystallize(self, user_id: str) -> bool:
        """Manually trigger crystallization, bypassing the time gate and the quantity gate."""
        return self._start_background_run(user_id, force=True)

    def _check_gates(self, user_id: str) -> bool:
        """Check the gating conditions; if they pass, start background crystallization."""
        return self._start_background_run(user_id, force=False)

    def _start_background_run(self, user_id: str, *, force: bool = False) -> bool:
        user_pending = self._try_mark_running(user_id, force=force)
        if user_pending <= 0:
            return False
        thread = threading.Thread(
            target=self._run_crystallization,
            args=(user_id,),
            daemon=True,
        )
        try:
            thread.start()
        except Exception as exc:
            logger.error("crystallizer: failed to start background thread: %s", exc)
            self._mark_not_running()
            return False
        logger.info(
            "crystallizer: started (user=%s, pending=%d, force=%s)",
            user_id,
            user_pending,
            force,
        )
        return True

    def _try_mark_running(self, user_id: str, *, force: bool = False) -> int:
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            if self._state.running:
                return 0
            if force:
                self._state.last_run.pop(user_id, None)
                self._state.last_check.pop(user_id, None)
                self._state.last_check_passed.pop(user_id, None)
                self._state.last_failed_attempt.pop(user_id, None)
            elif not self._time_gate(user_id):
                self._save_state_locked()
                return 0

            user_pending = len(self._state.pending_ids.get(user_id, []))
            if user_pending == 0:
                self._save_state_locked()
                return 0
            if not force and user_pending < self._threshold:
                self._save_state_locked()
                return 0

            self._state.running = True
            self._save_state_locked()
            return user_pending
        finally:
            self._lock.release()

    def _time_gate(self, user_id: str) -> bool:
        """Gate 1: time gate (per-user). With a 10-minute cache to avoid frequent recomputation."""
        now = time.time()
        last_check = self._state.last_check.get(user_id, 0.0)
        if now - last_check < 600:
            return self._state.last_check_passed.get(user_id, False)
        passed = True
        failed_at = self._state.last_failed_attempt.get(user_id, 0.0)
        if (
            self._failure_backoff_seconds > 0
            and failed_at
            and now - failed_at < self._failure_backoff_seconds
        ):
            passed = False
        user_last_run = self._state.last_run.get(user_id)
        if passed and user_last_run:
            try:
                last_run_ts = datetime.fromisoformat(user_last_run).timestamp()
                elapsed = now - last_run_ts
                passed = elapsed >= self._interval_seconds
            except (ValueError, OSError):
                passed = True
        self._state.last_check[user_id] = now
        self._state.last_check_passed[user_id] = passed
        if not passed:
            logger.debug(
                "结晶器: 时间门未通过 (user=%s, 距上次结晶不足 %gh)",
                user_id,
                self._interval_seconds / 3600,
            )
        return passed

    def _mark_not_running(self) -> None:
        with self._lock:
            self._state.running = False
            self._save_state_locked()

    def _save_state_locked(self) -> None:
        """Save the state (the caller must hold self._lock or be in the crystallization thread)."""
        try:
            _save_state(self._state, self._state_path)
        except OSError as exc:
            logger.error("结晶器: 状态文件写入失败: %s", exc)

    @staticmethod
    def _valid_embedding(value: Any) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        return vector if all(math.isfinite(item) for item in vector) else None

    def _fetch_pending_facts(
        self, backend: Any, pending_ids: list[str]
    ) -> tuple[list[dict[str, Any]], set[str], dict[str, list[float]]]:
        """Batch-fetch the raw memories to be processed and reuse their Qdrant vectors."""
        items: list[dict[str, Any]] | None = None
        batch_getter = getattr(backend, "get_memories_with_vectors_by_ids", None)
        if callable(batch_getter):
            try:
                items = list(batch_getter(pending_ids) or [])
            except Exception as exc:
                logger.warning(
                    "结晶器: 批量读取 raw 向量失败，降级为逐条读取并分批补算 embedding: %s",
                    exc,
                )

        if items is None:
            items = []
            for fact_id in pending_ids:
                try:
                    item = backend.get_memory(fact_id)
                    if item:
                        items.append(item)
                except Exception:
                    continue

        by_id = {
            str(item.get("id")): item for item in items if isinstance(item, dict) and item.get("id")
        }
        raw_facts: list[dict[str, Any]] = []
        fetched_ids: set[str] = set()
        vectors: dict[str, list[float]] = {}
        for fact_id in pending_ids:
            item = by_id.get(str(fact_id))
            if not item or not item.get("memory"):
                continue
            raw_facts.append(item)
            fetched_ids.add(str(fact_id))
            vector = self._valid_embedding(item.get("embedding"))
            if vector is not None:
                vectors[str(fact_id)] = vector
        return raw_facts, fetched_ids, vectors

    def _embed_texts_in_batches(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for index in range(0, len(texts), self._embedding_batch_size):
            batch = texts[index : index + self._embedding_batch_size]
            embedded = self._embed_fn(batch)
            if len(embedded) != len(batch):
                raise RuntimeError(
                    f"embedder returned {len(embedded)} vectors for {len(batch)} texts"
                )
            for value in embedded:
                vector = self._valid_embedding(value)
                if vector is None:
                    raise RuntimeError("embedder returned an empty or invalid vector")
                vectors.append(vector)
        return vectors

    def _load_clustering_embeddings(
        self,
        raw_facts: list[dict[str, Any]],
        existing_crystals: list[dict[str, Any]],
        raw_vectors: dict[str, list[float]],
    ) -> tuple[list[list[float]], list[list[float]]]:
        """Reuse projection vectors, only vectorizing in batches the entries that are missing or invalid."""
        content_hashes = {
            str(crystal.get("id")): str(metadata.get("content_hash"))
            for crystal in existing_crystals
            for metadata in [crystal.get("metadata", {}) or {}]
            if crystal.get("id") and metadata.get("content_hash")
        }
        try:
            crystal_vectors = self._ledger.crystal_cluster_vectors(content_hashes)
        except Exception as exc:
            crystal_vectors = {}
            logger.warning("结晶器: 读取 crystal 投影向量失败，将分批补算 embedding: %s", exc)

        texts = [str(fact["memory"]) for fact in raw_facts] + [
            _display_text(crystal) for crystal in existing_crystals
        ]
        vectors: list[list[float] | None] = [
            raw_vectors.get(str(fact.get("id"))) for fact in raw_facts
        ] + [
            self._valid_embedding(crystal_vectors.get(str(crystal.get("id"))))
            for crystal in existing_crystals
        ]
        missing = [index for index, vector in enumerate(vectors) if vector is None]
        if missing:
            embedded = self._embed_texts_in_batches([texts[index] for index in missing])
            for index, vector in zip(missing, embedded):
                vectors[index] = vector

        dimensions = {len(vector) for vector in vectors if vector is not None}
        reembedded_all = len(dimensions) != 1
        if reembedded_all:
            logger.warning(
                "结晶器: Qdrant 向量维度不一致 %s，将按当前模型分批重算本轮向量",
                sorted(dimensions),
            )
            vectors = self._embed_texts_in_batches(texts)

        resolved = [vector for vector in vectors if vector is not None]
        if len(resolved) != len(texts):
            raise RuntimeError("failed to resolve every clustering embedding")
        final_dimensions = {len(vector) for vector in resolved}
        if len(final_dimensions) != 1:
            raise RuntimeError(
                f"embedder returned inconsistent dimensions: {sorted(final_dimensions)}"
            )
        raw_count = len(raw_facts)
        raw_fallbacks = sum(index < raw_count for index in missing)
        crystal_fallbacks = len(missing) - raw_fallbacks
        reused_raw = 0 if reembedded_all else raw_count - raw_fallbacks
        reused_crystals = 0 if reembedded_all else len(existing_crystals) - crystal_fallbacks
        embedded_count = len(texts) if reembedded_all else len(missing)
        logger.info(
            "结晶器: 聚类向量复用 raw=%d/%d, crystal=%d/%d, 补算=%d, batch_size=%d",
            reused_raw,
            raw_count,
            reused_crystals,
            len(existing_crystals),
            embedded_count,
            self._embedding_batch_size,
        )
        return resolved[:raw_count], resolved[raw_count:]

    def _run_crystallization(self, user_id: str) -> None:
        """Crystallization pipeline entry (runs in a background thread)."""
        try:
            self._do_crystallize(user_id)
        except Exception as exc:
            logger.error("结晶失败: %s", exc, exc_info=True)
        finally:
            self._ledger.end_batch()
            self._mark_not_running()
            # After crystallization, recheck the gate: if new facts accumulated during the run
            # and the time gate has passed, trigger the next round immediately, to avoid the
            # pipeline stalling near the end of ingest with no one triggering it.
            # Clear the time-gate cache so the next _time_gate recomputes instead of reading a stale value.
            with self._lock:
                self._state.last_check.pop(user_id, None)
                self._state.last_check_passed.pop(user_id, None)
            if self._check_gates(user_id):
                logger.info("结晶器: 结束后立即触发下一轮 (user=%s)", user_id)

    def _do_crystallize(self, user_id: str) -> None:
        """Core crystallization pipeline logic. Only processes the specified user's pending facts."""
        backend = self._backend_accessor()
        # The batch id of this round spans all ledger writes, so the whole round can be rolled back at once
        self._ledger.begin_batch()

        with self._lock:
            pending_ids = list(self._state.pending_ids.get(user_id, []))
        logger.info("结晶器: 开始结晶, %d 条待处理事实 (user=%s)", len(pending_ids), user_id)

        raw_facts, fetched_ids, raw_vectors = self._fetch_pending_facts(backend, pending_ids)

        stale_count = len(pending_ids) - len(fetched_ids)
        if stale_count > 0:
            logger.info(
                "结晶器: %d 条 pending 事实已不存在于存储中，将清理 (user=%s)", stale_count, user_id
            )

        if not raw_facts:
            logger.info("结晶器: 无有效事实 (user=%s)，跳过", user_id)
            with self._lock:
                self._state.pending_ids[user_id] = []
                self._save_state_locked()
            return

        existing_crystals = self._ledger.current_crystals(user_id=user_id)

        logger.info(
            "结晶器: %d 条原始事实 + %d 条已有结晶 (user=%s)",
            len(raw_facts),
            len(existing_crystals),
            user_id,
        )

        if len(raw_facts) < self._min_cluster_size and not existing_crystals:
            logger.info(
                "结晶器: 原始事实不足 min_cluster_size=%d，等待更多 (user=%s)",
                self._min_cluster_size,
                user_id,
            )
            with self._lock:
                self._state.last_check.pop(user_id, None)
                self._state.last_check_passed.pop(user_id, None)
                self._save_state_locked()
            return

        try:
            raw_embeddings, crystal_embeddings = self._load_clustering_embeddings(
                raw_facts, existing_crystals, raw_vectors
            )
        except Exception as exc:
            logger.error("结晶器: embedding 失败: %s", exc)
            with self._lock:
                self._state.last_failed_attempt[user_id] = time.time()
                self._state.last_check.pop(user_id, None)
                self._state.last_check_passed.pop(user_id, None)
                self._save_state_locked()
            return

        clusters = self._cluster(raw_embeddings, crystal_embeddings, raw_facts)
        subject_split_count = 0
        if self._subject_split_enabled:
            clusters, subject_split_count = self._split_clusters_by_subject(clusters, raw_facts)
        logger.info("结晶器: 聚类产出 %d 个簇", len(clusters))

        created_count = 0
        absorbed_count = 0
        processed_raw_indices: set[int] = set()
        rejected_raw_indices: set[int] = set()
        failed_attempt_raw_indices: set[int] = set()
        audit_created: list[dict[str, Any]] = []
        audit_absorbed: list[dict[str, Any]] = []
        audit_failed: list[dict[str, Any]] = []
        audit_rejected: list[dict[str, Any]] = []
        audit_deferred: list[dict[str, Any]] = []
        audit_superseded: list[dict[str, Any]] = []
        oversize_absorb_blocked = 0
        type_absorb_blocked = 0
        latest_crystals = {c.get("id"): c for c in existing_crystals if c.get("id")}
        deleted_crystal_ids: set[str] = set()

        run_clusters = clusters[: self._max_clusters_per_run]
        deferred_clusters = max(0, len(clusters) - len(run_clusters))
        for cluster in run_clusters:
            raw_indices = cluster["raw_indices"]
            crystal_indices = cluster["crystal_indices"]

            cluster_raw = [raw_facts[i] for i in raw_indices]
            cluster_crystal = []
            for i in crystal_indices:
                crystal = existing_crystals[i]
                crystal_id = crystal.get("id")
                if crystal_id in deleted_crystal_ids:
                    continue
                cluster_crystal.append(latest_crystals.get(crystal_id, crystal))

            try:
                quality_result = self._quality_filter.screen(
                    raw_facts,
                    raw_indices,
                    cluster_crystal,
                    min_required_items=(1 if cluster_crystal else self._min_cluster_size),
                )
            except Exception as exc:
                logger.error("结晶器: 簇准入审查失败: %s", exc)
                failed_attempt_raw_indices.update(raw_indices)
                audit_failed.append(
                    {
                        "operation": "quality_screen",
                        "source_ids": [raw_facts[index].get("id") for index in raw_indices],
                        "error": str(exc),
                    }
                )
                continue

            quality_screen = quality_result.audit_record()
            rejected_raw_indices.update(quality_result.rejected_indices)
            failed_attempt_raw_indices.update(quality_result.deferred_indices)
            if quality_result.rejected_items:
                audit_rejected.append(quality_screen)
            if quality_result.deferred_indices:
                audit_deferred.append(quality_screen)
            if quality_result.decision != "crystallize":
                continue

            raw_indices = list(quality_result.accepted_indices)
            cluster_raw = [raw_facts[index] for index in raw_indices]

            if cluster_crystal and cluster_raw:
                try:
                    raw_pairs = list(zip(raw_indices, cluster_raw))
                    raw_asset_types = {idx: asset_type_for_memory(raw) for idx, raw in raw_pairs}

                    def target_score(candidate: dict[str, Any]) -> tuple[int, float]:
                        candidate_asset = asset_type_for_memory(candidate)
                        compatible = sum(
                            asset_types_absorb_compatible(candidate_asset, raw_type)
                            for raw_type in raw_asset_types.values()
                        )
                        meta = candidate.get("metadata", {}) or {}
                        confidence = meta.get("confidence", 0.5) if isinstance(meta, dict) else 0.5
                        return compatible, float(confidence or 0.5)

                    target = max(cluster_crystal, key=target_score)
                    target_asset_type = asset_type_for_memory(target)
                    compatible_pairs = [
                        (idx, raw)
                        for idx, raw in raw_pairs
                        if asset_types_absorb_compatible(target_asset_type, raw_asset_types[idx])
                    ]
                    compatible_indices = {idx for idx, _ in compatible_pairs}
                    blocked_pairs = [
                        (idx, raw) for idx, raw in raw_pairs if idx not in compatible_indices
                    ]
                    if blocked_pairs:
                        type_absorb_blocked += len(blocked_pairs)

                    if not compatible_pairs:
                        if len(blocked_pairs) >= self._min_cluster_size:
                            blocked_raw = [raw for _, raw in blocked_pairs]
                            record = self._create_crystal(blocked_raw, user_id)
                            record["type_absorb_blocked"] = True
                            record["blocked_by_crystal_id"] = target.get("id")
                            record["blocked_by_asset_type"] = target_asset_type
                            record["quality_screen"] = quality_screen
                            audit_created.append(record)
                            created_count += 1
                            processed_raw_indices.update(idx for idx, _ in blocked_pairs)
                        continue

                    if len(blocked_pairs) >= self._min_cluster_size:
                        blocked_raw = [raw for _, raw in blocked_pairs]
                        record = self._create_crystal(blocked_raw, user_id)
                        record["type_absorb_blocked"] = True
                        record["blocked_by_crystal_id"] = target.get("id")
                        record["blocked_by_asset_type"] = target_asset_type
                        record["quality_screen"] = quality_screen
                        audit_created.append(record)
                        created_count += 1
                        processed_raw_indices.update(idx for idx, _ in blocked_pairs)

                    absorb_raw_indices = [idx for idx, _ in compatible_pairs]
                    absorb_raw = [raw for _, raw in compatible_pairs]
                    target_meta = target.get("metadata", {}) or {}
                    if not isinstance(target_meta, dict):
                        target_meta = {}
                    target_source_ids = target_meta.get("source_ids", [])
                    if not isinstance(target_source_ids, list):
                        target_source_ids = []
                    if len(target_source_ids) >= self._max_source_ids_per_crystal:
                        record = self._create_crystal(absorb_raw, user_id)
                        record["oversize_absorb_blocked"] = True
                        record["quality_screen"] = quality_screen
                        audit_created.append(record)
                        created_count += 1
                        oversize_absorb_blocked += 1
                        processed_raw_indices.update(absorb_raw_indices)
                        continue
                    obsolete_crystals = [
                        c
                        for c in cluster_crystal
                        if c.get("id") != target.get("id")
                        and asset_types_absorb_compatible(
                            target_asset_type, asset_type_for_memory(c)
                        )
                    ]
                    facts_to_absorb = list(absorb_raw)
                    for obsolete in obsolete_crystals:
                        meta = obsolete.get("metadata", {}) or {}
                        if not isinstance(meta, dict):
                            meta = {}
                        text = _display_text(obsolete)
                        facets = _normalize_facets(meta.get("facets", {}))
                        facet_text = ", ".join(_flatten_facets(facets))
                        if facet_text:
                            text = f"{text}\nFacets: {facet_text}"
                        facts_to_absorb.append(
                            {
                                "id": obsolete.get("id"),
                                "memory": text,
                                "metadata": {"source_ids": meta.get("source_ids", [])},
                            }
                        )
                    record = self._absorb_crystal(
                        target,
                        facts_to_absorb,
                        superseded_crystals=obsolete_crystals,
                    )
                    record["quality_screen"] = quality_screen
                    audit_absorbed.append(record)
                    absorbed_count += 1
                    processed_raw_indices.update(absorb_raw_indices)
                    fresh_targets = self._ledger.current_crystals(user_id=user_id)
                    fresh_target = next(
                        (item for item in fresh_targets if item.get("id") == target.get("id")),
                        target,
                    )
                    latest_crystals[target["id"]] = fresh_target
                    for obsolete in obsolete_crystals:
                        obsolete_id = obsolete.get("id")
                        if obsolete_id and obsolete_id not in deleted_crystal_ids:
                            deleted_crystal_ids.add(obsolete_id)
                    audit_superseded.extend(record.get("superseded", []))
                except Exception as exc:
                    logger.error(
                        "结晶器: absorb 失败 (crystal=%s): %s", cluster_crystal[0].get("id"), exc
                    )
                    failed_attempt_raw_indices.update(raw_indices)
                    audit_failed.append(
                        {
                            "operation": "absorb",
                            "crystal_id": cluster_crystal[0].get("id"),
                            "source_ids": [f.get("id") for f in cluster_raw],
                            "error": str(exc),
                        }
                    )
            elif not cluster_crystal and len(cluster_raw) >= self._min_cluster_size:
                try:
                    record = self._create_crystal(cluster_raw, user_id)
                    record["quality_screen"] = quality_screen
                    audit_created.append(record)
                    created_count += 1
                    processed_raw_indices.update(raw_indices)
                except Exception as exc:
                    logger.error("结晶器: create 失败: %s", exc)
                    failed_attempt_raw_indices.update(raw_indices)
                    audit_failed.append(
                        {
                            "operation": "create",
                            "source_ids": [f.get("id") for f in cluster_raw],
                            "error": str(exc),
                        }
                    )

        processed_ids = {raw_facts[i]["id"] for i in processed_raw_indices if i < len(raw_facts)}
        rejected_ids = {raw_facts[i]["id"] for i in rejected_raw_indices if i < len(raw_facts)}
        failed_attempt_ids = {
            raw_facts[i]["id"] for i in failed_attempt_raw_indices if i < len(raw_facts)
        }
        stale_ids = set(pending_ids) - fetched_ids
        with self._lock:
            remaining, evicted_ids = finalize_crystallization_state(
                self._state,
                user_id=user_id,
                processed_ids=processed_ids,
                rejected_ids=rejected_ids,
                stale_ids=stale_ids,
                failed_attempt_ids=failed_attempt_ids,
                max_fact_attempts=self._max_fact_attempts,
                created_count=created_count,
                absorbed_count=absorbed_count,
                failed_count=len(audit_failed),
                completed_at=datetime.now(timezone.utc).isoformat(),
                failed_at=time.time(),
            )
            self._save_state_locked()

        try:
            audit_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "input_facts": len(raw_facts),
                "existing_crystals": len(existing_crystals),
                "clusters": len(clusters),
                "processed_clusters": len(run_clusters),
                "deferred_clusters": deferred_clusters,
                "cluster_diagnostics": self._last_cluster_diagnostics,
                "created_count": created_count,
                "absorbed_count": absorbed_count,
                "failed_count": len(audit_failed),
                "rejected_count": len(rejected_ids),
                "deferred_count": len(failed_attempt_ids),
                "evicted_count": len(evicted_ids),
                "asset_type_counts": self._asset_type_counts(audit_created, audit_absorbed),
                "subject_split_count": subject_split_count,
                "oversize_absorb_blocked": oversize_absorb_blocked,
                "type_absorb_blocked": type_absorb_blocked,
                "batch_id": self._ledger.batch_id,
                "solidification_superseded": audit_superseded,
                "created": audit_created,
                "absorbed": audit_absorbed,
                "rejected": audit_rejected,
                "deferred": audit_deferred,
                "evicted_source_ids": sorted(evicted_ids),
                "failed": audit_failed,
                "remaining_pending": remaining,
                "crystallizer_stats": self.stats(),
                "composition_after_run": self.get_composition(user_id),
            }
            if self._solidification is not None:
                audit_record["solidification_state"] = self._ledger.state()
            _write_audit_record(
                self._audit_path,
                audit_record,
                max_bytes=self._audit_max_bytes,
                backups=self._audit_backups,
            )
        except OSError as exc:
            logger.error("结晶器: 审计日志写入失败: %s", exc)

        logger.info(
            "结晶完成: 新建 %d, absorb %d, 剩余待处理 %d (user=%s)",
            created_count,
            absorbed_count,
            remaining,
            user_id,
        )

    def _cluster(
        self,
        raw_embeddings: list[list[float]],
        crystal_embeddings: list[list[float]],
        raw_facts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, list[int]]]:
        raw_subjects = None
        if self._subject_split_enabled and raw_facts is not None:
            raw_subjects = [subject_key_for_memory(fact) for fact in raw_facts]
        raw_asset_types = (
            [asset_type_for_memory(fact) for fact in raw_facts] if raw_facts is not None else None
        )
        clusters, diagnostics = cluster_similarity_graph(
            raw_embeddings,
            crystal_embeddings,
            min_cluster_size=self._min_cluster_size,
            cluster_create_similarity=self._cluster_create_similarity,
            cluster_absorb_similarity=self._cluster_absorb_similarity,
            cluster_min_avg_similarity=self._cluster_min_avg_similarity,
            cluster_max_size=self._cluster_max_size,
            raw_subjects=raw_subjects,
            raw_asset_types=raw_asset_types,
        )
        self._last_cluster_diagnostics = diagnostics
        return clusters

    @staticmethod
    def _avg_similarity(similarity: Any, indices: list[int]) -> float:
        return avg_similarity(similarity, indices)

    def _split_clusters_by_subject(
        self,
        clusters: list[dict[str, list[int]]],
        raw_facts: list[dict[str, Any]],
    ) -> tuple[list[dict[str, list[int]]], int]:
        split_clusters: list[dict[str, list[int]]] = []
        split_count = 0
        for cluster in clusters:
            raw_indices = cluster.get("raw_indices", [])
            if len(raw_indices) < self._min_cluster_size * 2:
                split_clusters.append(cluster)
                continue

            groups: dict[str, list[int]] = {}
            unknown: list[int] = []
            for idx in raw_indices:
                subject = subject_key_for_memory(raw_facts[idx])
                if subject:
                    groups.setdefault(subject, []).append(idx)
                else:
                    unknown.append(idx)

            if (
                len(groups) <= 1
                or unknown
                or any(len(indices) < self._min_cluster_size for indices in groups.values())
            ):
                split_clusters.append(cluster)
                continue

            for indices in groups.values():
                split_clusters.append(
                    {
                        "raw_indices": indices,
                        "crystal_indices": list(cluster.get("crystal_indices", [])),
                    }
                )
            split_count += len(groups) - 1

        return split_clusters, split_count

    @staticmethod
    def _asset_type_counts(*groups: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for group in groups:
            for item in group:
                asset_type = str(item.get("asset_type") or "unknown")
                counts[asset_type] = counts.get(asset_type, 0) + 1
        return counts

    @staticmethod
    def _validate_merged(merged: dict[str, Any], max_text_chars: int = 420) -> dict[str, Any]:
        return normalize_merged_crystal(merged, max_text_chars=max_text_chars)

    @staticmethod
    def _validate_retention_judge(judge: dict[str, Any]) -> dict[str, Any]:
        return validate_retention_judge(judge)

    def _judge_retention(
        self,
        old_text: str,
        old_facets: dict[str, list[str]],
        new_texts: list[str],
        merged: dict[str, Any],
        old_asset: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return judge_retention(
            self._llm_fn,
            old_text=old_text,
            old_facets=old_facets,
            old_asset=old_asset or {},
            new_texts=new_texts,
            merged=merged,
        )

    def _validate_or_repair_retention(
        self,
        old_text: str,
        old_facets: dict[str, list[str]],
        new_texts: list[str],
        merged: dict[str, Any],
        old_asset: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return validate_or_repair_retention(
            self._llm_fn,
            old_text=old_text,
            old_facets=old_facets,
            old_asset=old_asset or {},
            new_texts=new_texts,
            merged=merged,
            max_text_chars=self._max_display_chars,
        )

    def _absorb_crystal(
        self,
        old_crystal: dict[str, Any],
        new_facts: list[dict[str, Any]],
        *,
        superseded_crystals: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Merge new facts into an existing crystal entry. Returns an audit record."""
        old_text = _clip_text(_display_text(old_crystal), self._max_crystal_chars)
        new_texts = [_clip_text(f.get("memory", ""), self._max_fact_chars) for f in new_facts]
        fact_context, evidence_texts = self._quality_filter.fact_context(new_facts)

        # Detect the dominant input language (existing crystal + new facts), constraining the crystal output language to be consistent
        language = detect_dominant_language(old_text, *new_texts)
        language_label = "中文" if language == "zh" else "英文"

        merged = self._llm_fn(
            MERGE_SYSTEM_PROMPT,
            MERGE_USER_TEMPLATE.format(
                old_text,
                fact_context,
                language=language_label,
            ),
            MERGE_JSON_SCHEMA,
        )
        merged = self._validate_merged(merged, self._max_display_chars)

        old_meta = old_crystal.get("metadata", {})
        if not isinstance(old_meta, dict):
            old_meta = {}
        old_facets = _normalize_facets(old_meta.get("facets", {}))
        old_asset = old_meta.get("asset", {})
        if not isinstance(old_asset, dict):
            old_asset = {}
        merged, retention_check = self._validate_or_repair_retention(
            old_text=old_text,
            old_facets=old_facets,
            new_texts=evidence_texts,
            merged=merged,
            old_asset=old_asset,
        )
        self._quality_filter.validate_candidate(merged)

        old_source_ids = old_meta.get("source_ids", [])
        if not isinstance(old_source_ids, list):
            old_source_ids = []
        new_source_ids = list(old_source_ids)
        for fact in new_facts:
            fact_meta = fact.get("metadata", {}) or {}
            source_ids = fact_meta.get("source_ids") if isinstance(fact_meta, dict) else None
            if isinstance(source_ids, list) and source_ids:
                new_source_ids.extend(source_ids)
            elif fact.get("id"):
                new_source_ids.append(fact["id"])
        new_source_ids = list(dict.fromkeys(new_source_ids))

        old_version = old_meta.get("version", 1)
        updated_metadata = {
            "layer": "crystallized",
            "schema_version": self._schema_version,
            "knowledge_type": merged["type"],
            "asset_type": merged["asset_type"],
            "asset": merged["asset"],
            "subject": merged["subject"],
            "confidence": merged["confidence"],
            "source_ids": new_source_ids,
            "source_count": len(new_source_ids),
            "evidence_source_ids": new_source_ids,
            "version": old_version + 1,
            "status": "active",
            "crystallized_at": datetime.now(timezone.utc).isoformat(),
            "display_text": merged["text"],
            "facets": merged["facets"],
        }
        for scope_key in ("user_id", "agent_id", "run_id"):
            if scope_key in old_meta:
                updated_metadata[scope_key] = old_meta[scope_key]
            elif old_crystal.get(scope_key):
                updated_metadata[scope_key] = old_crystal[scope_key]

        logger.info(
            "结晶器: absorb %d 条事实 → crystal %s (v%d)",
            len(new_facts),
            old_crystal["id"][:8],
            updated_metadata["version"],
        )

        record = {
            "crystal_id": old_crystal["id"],
            "old_text": old_text,
            "new_text": merged["text"],
            "added_facts": new_texts,
            "version": f"{old_version}→{old_version + 1}",
            "type": merged["type"],
            "asset_type": merged["asset_type"],
            "asset": merged["asset"],
            "confidence": merged["confidence"],
            "facets": merged["facets"],
            "retention_check": retention_check,
        }
        ledger_record = self._ledger.absorb(
            merged,
            source_ids=new_source_ids,
            crystal_id=old_crystal["id"],
            superseded_crystal_ids=[
                str(item["id"]) for item in (superseded_crystals or []) if item.get("id")
            ],
            scope={
                key: updated_metadata[key]
                for key in ("user_id", "agent_id", "run_id")
                if updated_metadata.get(key)
            },
            audit={
                "retention_check": retention_check,
                "maturity": {"evidence_run_ids": _evidence_run_ids(new_facts)},
            },
        )
        record["solidification"] = ledger_record
        record["crystal_id"] = ledger_record["crystal_id"]
        record["superseded"] = list(ledger_record.get("superseded") or [])
        return record

    def _create_crystal(self, facts: list[dict[str, Any]], user_id: str) -> dict[str, Any]:
        """Create a crystal entry from a set of new facts. Returns an audit record."""
        texts = [_clip_text(f.get("memory", ""), self._max_fact_chars) for f in facts]
        fact_context, evidence_texts = self._quality_filter.fact_context(facts)

        # Detect the dominant input language, constraining the crystal output language to be consistent
        language = detect_dominant_language(*texts)
        language_label = "中文" if language == "zh" else "英文"

        merged = self._llm_fn(
            MERGE_SYSTEM_PROMPT,
            MERGE_USER_TEMPLATE.format(
                "(无)",
                fact_context,
                language=language_label,
            ),
            MERGE_JSON_SCHEMA,
        )
        merged = self._validate_merged(merged, self._max_display_chars)
        merged, retention_check = self._validate_or_repair_retention(
            old_text="(无)",
            old_facets={key: [] for key in FACET_KEYS},
            new_texts=evidence_texts,
            merged=merged,
        )
        self._quality_filter.validate_candidate(merged)

        crystal_metadata = {
            "layer": "crystallized",
            "schema_version": self._schema_version,
            "knowledge_type": merged["type"],
            "asset_type": merged["asset_type"],
            "asset": merged["asset"],
            "subject": merged["subject"],
            "confidence": merged["confidence"],
            "source_ids": [f["id"] for f in facts],
            "source_count": len(facts),
            "evidence_source_ids": [f["id"] for f in facts],
            "version": 1,
            "status": "active",
            "crystallized_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "display_text": merged["text"],
            "facets": merged["facets"],
        }

        logger.info(
            "结晶器: 新建结晶 (type=%s, sources=%d)",
            merged["type"],
            len(facts),
        )

        record = {
            "text": merged["text"],
            "type": merged["type"],
            "asset_type": merged["asset_type"],
            "asset": merged["asset"],
            "confidence": merged["confidence"],
            "facets": merged["facets"],
            "source_facts": texts,
            "retention_check": retention_check,
        }
        ledger_record = self._ledger.create(
            merged,
            source_ids=crystal_metadata["source_ids"],
            user_id=user_id,
            audit={
                "retention_check": retention_check,
                "maturity": {"evidence_run_ids": _evidence_run_ids(facts)},
            },
        )
        record["solidification"] = ledger_record
        record["crystal_id"] = ledger_record["crystal_id"]
        return record
