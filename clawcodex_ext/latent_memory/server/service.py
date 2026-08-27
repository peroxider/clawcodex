from __future__ import annotations

import logging
import math
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Any

from clawcodex_ext.latent_memory.server.backends import (
    MemoryBackend,
    Mem0MemoryBackend,
    build_scope_filters,
)
from clawcodex_ext.latent_memory.server.lib.salience_gate import SalienceGate
from clawcodex_ext.latent_memory.server.schemas import AddRequest, SearchRequest
from clawcodex_ext.latent_memory.server.token_usage import token_usage_tracker

logger = logging.getLogger("memory-server")

_RRF_K = 60
_MAX_CANDIDATE_RESULTS = 1
_STATUS_WEIGHTS = {
    "candidate": 0.78,
    "active": 1.0,
    "canonical": 1.02,
}


def _safe_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return score if math.isfinite(score) else default


def _clamp_score(value: Any) -> float:
    return max(0.0, min(1.0, _safe_score(value)))


def _normalized_text(value: Any) -> str:
    return re.sub(r"\W+", " ", str(value or "").casefold()).strip()


def _match_units(value: Any) -> set[str]:
    text = str(value or "").casefold()
    units = set(re.findall(r"[a-z0-9_.:/%-]{2,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(segment) == 1:
            units.add(segment)
        else:
            units.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return units


def _clause_matches(query: str, clause: str) -> bool:
    query_text = re.sub(r"\s+", " ", query).strip().casefold()
    clause_text = re.sub(r"\s+", " ", clause).strip().casefold()
    if not query_text or not clause_text:
        return False
    if clause_text in query_text:
        return True
    clause_units = _match_units(clause_text)
    if not clause_units:
        return False
    overlap = len(clause_units.intersection(_match_units(query_text))) / len(clause_units)
    return overlap >= 0.6


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = []
    return [str(item).strip() for item in values if str(item).strip()]


def _applicability_adjustment(
    query: str, metadata: dict[str, Any]
) -> tuple[float, dict[str, list[str]]]:
    applicability = metadata.get("applicability")
    applicability = applicability if isinstance(applicability, dict) else {}
    matched = {
        key: [
            clause
            for clause in _string_list(applicability.get(key))
            if _clause_matches(query, clause)
        ]
        for key in ("applies_when", "does_not_apply_when", "known_exceptions")
    }
    adjustment = 0.03 if matched["applies_when"] else 0.0
    if matched["does_not_apply_when"]:
        adjustment -= 0.25
    if matched["known_exceptions"]:
        adjustment -= 0.15
    return adjustment, matched


def _timed_call(call: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call(*args, **kwargs)
    return result, round((time.perf_counter() - started) * 1000, 3)


def _normalize_result_scores(result: Any) -> Any:
    def normalize_item(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        item = dict(item)
        item["score"] = _safe_score(item.get("score"))
        return item

    if isinstance(result, dict) and isinstance(result.get("results"), list):
        result = dict(result)
        result["results"] = [normalize_item(item) for item in result["results"]]
    elif isinstance(result, list):
        result = [normalize_item(item) for item in result]
    return result


def _apply_display_text(item: Any) -> Any:
    """For crystallized memories returned to the caller, use metadata.display_text."""
    if not isinstance(item, dict):
        return item
    meta = item.get("metadata", {}) or {}
    if isinstance(meta, dict):
        display = meta.get("display_text")
        if isinstance(display, str) and display.strip():
            item = dict(item)
            item["embedding_memory"] = item.get("memory", "")
            item["memory"] = display.strip()
    return item


def _apply_display_texts(result: Any) -> Any:
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        result = dict(result)
        result["results"] = [_apply_display_text(item) for item in result["results"]]
    elif isinstance(result, list):
        result = [_apply_display_text(item) for item in result]
    return result


def _has_search_scope(request: SearchRequest) -> bool:
    if request.user_id or request.agent_id or request.run_id:
        return True
    filters = request.filters or {}
    return any(filters.get(key) for key in ("user_id", "agent_id", "run_id"))


class MemoryServiceError(Exception):
    """Raised when the underlying memory backend fails."""


class MemoryNotReadyError(MemoryServiceError):
    """Raised when the memory backend has not been initialized."""


class MissingMemoryScopeError(MemoryServiceError):
    """Raised when an operation needs user_id, agent_id, or run_id but none are provided."""


class MemoryService:
    """Memory business layer -- the middle layer between the transport layer and the backend.

    Responsible for lifecycle management, scope parameter validation, and readiness checks. The
    actual CRUD operations are delegated to a replaceable MemoryBackend implementation. Different
    backends can be injected via the constructor's backend parameter without modifying this class.
    """

    def __init__(
        self,
        config: dict[str, Any],
        backend: MemoryBackend | None = None,
        salience_gate: SalienceGate | None = None,
        crystallizer: Any | None = None,
        default_search_strategy: str = "layered",
        min_score: float | None = None,
        solidification: Any | None = None,
        search_workers: int = 4,
        raw_search_timeout_seconds: float = 10.0,
        crystal_search_timeout_seconds: float = 10.0,
        crystal_candidate_limit: int = 20,
        provenance_lookup_limit: int = 30,
        provenance_per_crystal: int = 5,
        validity_config: dict[str, Any] | None = None,
    ):
        self.config = config
        self.backend = backend or Mem0MemoryBackend(config)
        _add_retry = (config or {}).get("add_retry", {}) or {}
        self._add_retry_max_retries = max(0, int(_add_retry.get("max_retries", 0)))
        self._add_retry_backoff = max(0.0, float(_add_retry.get("backoff_base_seconds", 4.0)))
        self.salience_gate = salience_gate
        self.crystallizer = crystallizer
        # Crystallization authority boundary. Raw memories remain owned by the backend.
        self.solidification = solidification
        self._validity_config = dict(validity_config or {})
        self._default_search_strategy = default_search_strategy
        self._min_score = min_score
        self._raw_search_timeout = max(0.05, float(raw_search_timeout_seconds))
        self._crystal_search_timeout = max(0.05, float(crystal_search_timeout_seconds))
        self._crystal_candidate_limit = max(1, int(crystal_candidate_limit))
        self._provenance_lookup_limit = max(0, int(provenance_lookup_limit))
        self._provenance_per_crystal = max(0, int(provenance_per_crystal))
        self._search_executor = ThreadPoolExecutor(
            max_workers=max(2, int(search_workers)),
            thread_name_prefix="memory-layer-search",
        )
        self._search_failure_lock = threading.Lock()
        self._search_failures = {
            "raw_error": 0,
            "raw_timeout": 0,
            "crystal_error": 0,
            "crystal_timeout": 0,
            "total_failure": 0,
        }

    @property
    def ready(self) -> bool:
        """Whether the backend has finished initializing."""
        return self.backend.ready

    def start(self) -> None:
        """Initialize the backend (called at startup)."""
        self.backend.start()

    def stop(self) -> None:
        """Shut down the backend and release resources (called at shutdown)."""
        logger.info("关闭记忆服务")
        self._search_executor.shutdown(wait=False, cancel_futures=True)
        if self.solidification is not None:
            try:
                self.solidification.close()
            except Exception as exc:
                logger.warning("关闭固化层失败: %s", exc)
        self.backend.stop()

    def _add_with_retry(self, request: AddRequest) -> Any:
        """Call the backend write; when results are empty, retry the whole add with exponential backoff as needed.

        mem0 silently converts "empty extraction / semantic dedup / extraction LLM error" into empty
        results, which cannot be distinguished externally. Retrying the whole add is safe (mem0 dedups
        by hash, so no duplicate memories are created); therefore retry only triggers on empty results.
        max_retries=0 means no retry.
        """
        total_attempts = self._add_retry_max_retries + 1
        result: Any = None
        for attempt in range(1, total_attempts + 1):
            result = self.backend.add_memories(request)
            token_usage_tracker.record_add_request(forwarded=True)
            if not (isinstance(result, dict) and not result.get("results")):
                return result
            if attempt < total_attempts:
                wait = self._add_retry_backoff * (2 ** (attempt - 1))
                logger.warning(
                    "add 返回空 results（疑似抽取 LLM 瞬时失败），%.1fs 后重试 %d/%d",
                    wait,
                    attempt,
                    total_attempts,
                )
                time.sleep(wait)
        return result

    def add_memories(self, request: AddRequest) -> Any:
        """Write the conversation and trigger memory extraction.

        If a salience_gate is injected, filter out noisy messages before handing to the backend.
        If a crystallizer is injected, notify it for crystallization after writing.
        """
        self.ensure_ready()
        if not (request.user_id or request.agent_id or request.run_id):
            raise MissingMemoryScopeError("写入记忆至少需要提供 user_id、agent_id 或 run_id 之一")
        if self.salience_gate is not None:
            gate_result = self.salience_gate.filter_messages(request.messages)
            if gate_result.skipped:
                token_usage_tracker.record_add_request(forwarded=False)
                logger.info("门控: 跳过请求 (user=%s)", request.user_id or "?")
                return {"results": []}
            if len(gate_result.filtered_messages) < len(request.messages) or (
                gate_result.filtered_messages != request.messages
            ):
                logger.info(
                    "门控: %d→%d 条消息 (user=%s)",
                    len(request.messages),
                    len(gate_result.filtered_messages),
                    request.user_id or "?",
                )
                request = AddRequest(
                    messages=gate_result.filtered_messages,
                    user_id=request.user_id,
                    agent_id=request.agent_id,
                    run_id=request.run_id,
                    metadata=request.metadata,
                    timestamp=request.timestamp,
                    observation_date=request.observation_date,
                    custom_instructions=request.custom_instructions,
                )
        if self.crystallizer is not None or self.solidification is not None:
            meta = dict(request.metadata or {})
            meta["layer"] = "raw"
            request = AddRequest(
                messages=request.messages,
                user_id=request.user_id,
                agent_id=request.agent_id,
                run_id=request.run_id,
                metadata=meta,
                timestamp=request.timestamp,
                observation_date=request.observation_date,
                custom_instructions=request.custom_instructions,
            )

        result = self._add_with_retry(request)

        if isinstance(result, dict) and not result.get("results"):
            # mem0 silently returns empty results for "empty extraction / dedup / extraction LLM error";
            # its own logs do not cover the empty-extraction path, so add an observation point here to
            # reconcile client failures.
            text_preview = "; ".join(
                str(message.get("content", "")) for message in request.messages
            )[:120]
            logger.warning(
                "add 返回空 results（mem0 抽取为空/语义去重/抽取异常）: user=%s, label=%s, text=%s",
                request.user_id or "?",
                (request.metadata or {}).get("validity_eval_label", "?"),
                text_preview,
            )

        if self.crystallizer is not None and result:
            new_ids = [
                r["id"]
                for r in result.get("results", [])
                if r.get("event") in ("ADD", "UPDATE") and r.get("id")
            ]
            if new_ids:
                user_id = request.user_id or "default"
                self.crystallizer.notify_new_facts(user_id, new_ids)

        return result

    def search_memories(self, request: SearchRequest) -> Any:
        """Retrieve memories by semantic similarity, supporting layered search strategies."""
        self.ensure_ready()
        if not _has_search_scope(request):
            raise MissingMemoryScopeError("检索记忆至少需要提供 user_id、agent_id 或 run_id 之一")
        if self.crystallizer is None and self.solidification is None:
            return self._search_standard(request)
        strategy = request.search_strategy or self._default_search_strategy
        if strategy == "layered":
            return self._search_layered(request)
        if strategy == "crystal_boost":
            return self._search_crystal_boost(request)
        raise MemoryServiceError(f"Unsupported search strategy: {strategy}")

    def _search_standard(self, request: SearchRequest) -> Any:
        """Search without using the crystallization-layer filter."""
        result = self.backend.search_memories(request)
        result = _normalize_result_scores(result)
        result = self._apply_min_score_filter(result)
        return _apply_display_texts(result)

    def _search_layered(self, request: SearchRequest) -> dict[str, Any]:
        """Search both layers without backend rerank, then fuse them in one pass."""
        if not (
            self.solidification is not None
            and getattr(self.solidification, "vector_projection_enabled", False)
        ):
            return self._search_raw_only(request, reason="vector_projection_unavailable")

        crystal_limit = min(request.limit, self._crystal_candidate_limit)
        # Mem0 rerank scores and Qdrant cosine scores are not comparable. So both candidate generators
        # return vector-scale scores; the cross-layer fusion below is the sole responsibility of this service.
        raw_filters = dict(request.filters or {})
        # Maturity status belongs to the ledger crystallization. Applying it to raw Mem0
        # data would accidentally remove the safe fallback layer.
        raw_filters.pop("status", None)
        raw_request = SearchRequest(
            query=request.query,
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            filters=raw_filters or None,
            limit=request.limit,
            rerank=False,
            search_strategy=request.search_strategy,
        )
        total_started = time.perf_counter()
        raw_future = self._search_executor.submit(
            _timed_call, self.backend.search_memories, raw_request
        )
        crystal_future = self._search_executor.submit(
            _timed_call,
            self.solidification.search_crystals,
            request.query,
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            filters=request.filters,
            limit=crystal_limit,
        )
        futures = {
            "raw": (raw_future, self._raw_search_timeout),
            "crystal": (crystal_future, self._crystal_search_timeout),
        }
        layer_results: dict[str, Any] = {}
        layer_ms: dict[str, float | None] = {"raw": None, "crystal": None}
        layer_status: dict[str, str] = {}
        layer_errors: dict[str, str] = {}
        by_future = {
            future: (layer, timeout_seconds) for layer, (future, timeout_seconds) in futures.items()
        }
        deadlines = {
            future: total_started + timeout_seconds
            for future, (_, timeout_seconds) in by_future.items()
        }
        pending = set(by_future)
        while pending:
            completed = {future for future in pending if future.done()}
            if not completed:
                now = time.perf_counter()
                expired = {future for future in pending if deadlines[future] <= now}
                for future in expired:
                    layer, timeout_seconds = by_future[future]
                    future.cancel()
                    layer_status[layer] = "timeout"
                    layer_errors[layer] = f"exceeded {timeout_seconds:.3f}s"
                    self._record_search_failure(f"{layer}_timeout")
                pending.difference_update(expired)
                if not pending:
                    break
                if expired:
                    continue
                timeout = max(0.0, min(deadlines[future] for future in pending) - now)
                completed, _ = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                if not completed:
                    continue

            for future in completed:
                pending.discard(future)
                layer, timeout_seconds = by_future[future]
                try:
                    result, elapsed_ms = future.result()
                    layer_ms[layer] = elapsed_ms
                    if (
                        time.perf_counter() > deadlines[future]
                        or elapsed_ms > timeout_seconds * 1000
                    ):
                        layer_status[layer] = "timeout"
                        layer_errors[layer] = f"completed in {elapsed_ms:.3f}ms"
                        self._record_search_failure(f"{layer}_timeout")
                    else:
                        layer_results[layer] = result
                        layer_status[layer] = "ok"
                except Exception as exc:
                    layer_status[layer] = "error"
                    layer_errors[layer] = str(exc)
                    self._record_search_failure(f"{layer}_error")
                    logger.warning("%s memory search failed: %s", layer, exc)

        if not layer_results:
            self._record_search_failure("total_failure")
            raise MemoryServiceError(
                "all memory retrieval layers failed: "
                + "; ".join(f"{key}={value}" for key, value in layer_errors.items())
            )

        raw_result = layer_results.get("raw", {"results": []})
        crystal_result = layer_results.get("crystal", {"results": []})

        raw_list = _normalize_result_scores(
            raw_result.get("results", []) if isinstance(raw_result, dict) else []
        )
        crystal_list = _normalize_result_scores(
            crystal_result.get("results", []) if isinstance(crystal_result, dict) else []
        )
        return self._merge_layered_results(
            crystal_list,
            raw_list,
            request,
            diagnostics={
                "path": "independent_projection",
                "requested_rerank": bool(request.rerank),
                "backend_rerank_applied": False,
                "raw_ms": layer_ms["raw"],
                "crystal_ms": layer_ms["crystal"],
                "layers": layer_status,
                "layer_errors": layer_errors,
                "partial": len(layer_results) == 1,
                "failure_counts": self._search_failure_snapshot(),
                "parallel_total_ms": round((time.perf_counter() - total_started) * 1000, 3),
            },
        )

    def _search_raw_only(self, request: SearchRequest, *, reason: str) -> dict[str, Any]:
        """Safe degradation path: use raw evidence only, never legacy crystallization."""
        raw_filters = dict(request.filters or {})
        raw_filters.pop("status", None)
        raw_request = SearchRequest(
            query=request.query,
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            filters=raw_filters or None,
            limit=request.limit,
            rerank=request.rerank,
        )
        started = time.perf_counter()
        future = self._search_executor.submit(
            _timed_call, self.backend.search_memories, raw_request
        )
        done, _ = wait([future], timeout=self._raw_search_timeout)
        if future not in done:
            future.cancel()
            self._record_search_failure("raw_timeout")
            self._record_search_failure("total_failure")
            raise MemoryServiceError(
                f"raw memory retrieval timed out after {self._raw_search_timeout:.3f}s"
            )
        try:
            raw_result, raw_ms = future.result()
        except Exception as exc:
            self._record_search_failure("raw_error")
            self._record_search_failure("total_failure")
            raise MemoryServiceError(f"raw memory retrieval failed: {exc}") from exc
        result = _normalize_result_scores(raw_result)
        result = self._apply_min_score_filter(result)
        result = _apply_display_texts(result)
        if not isinstance(result, dict):
            result = {"results": result if isinstance(result, list) else []}
        result["diagnostics"] = {
            "path": "raw_only",
            "reason": reason,
            "partial": True,
            "layers": {"raw": "ok", "crystal": "unavailable"},
            "raw_ms": raw_ms,
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
            "failure_counts": self._search_failure_snapshot(),
        }
        return result

    def _record_search_failure(self, key: str) -> None:
        with self._search_failure_lock:
            self._search_failures[key] = self._search_failures.get(key, 0) + 1

    def _search_failure_snapshot(self) -> dict[str, int]:
        with self._search_failure_lock:
            return dict(self._search_failures)

    def _batch_get_memories(self, memory_ids: list[str]) -> list[dict[str, Any]]:
        """Read provenance sources through the required backend batch API."""
        return list(self.backend.get_memories_by_ids(memory_ids) or [])

    def _merge_layered_results(
        self,
        crystal_list: list[dict[str, Any]],
        raw_list: list[dict[str, Any]],
        request: SearchRequest,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fuse the two candidate lists, dedup by lineage, then fill in provenance info."""

        report = dict(diagnostics or {})
        report.update(
            {
                "fusion": "dense_weighted_rrf_v1",
                "raw_candidates": len(raw_list),
                "crystal_candidates": len(crystal_list),
                "candidate_crystals": sum(
                    (item.get("metadata") or {}).get("status") == "candidate"
                    for item in crystal_list
                    if isinstance(item, dict) and isinstance(item.get("metadata") or {}, dict)
                ),
            }
        )
        dropped: list[dict[str, str]] = []
        ranked: list[dict[str, Any]] = []

        for layer, items in (("crystal", crystal_list), ("raw", raw_list)):
            for rank, original in enumerate(items, 1):
                if not isinstance(original, dict):
                    continue
                item = dict(original)
                metadata = dict(item.get("metadata") or {})
                metadata.setdefault("layer", "crystallized" if layer == "crystal" else "raw")
                dense_score = _clamp_score(item.get("score"))
                rank_score = (_RRF_K + 1) / (_RRF_K + rank)
                status = str(metadata.get("status") or "active") if layer == "crystal" else "raw"
                status_weight = _STATUS_WEIGHTS.get(status, 1.0)
                applicability_delta, applicability_matches = _applicability_adjustment(
                    request.query, metadata
                )
                fused_score = _clamp_score(
                    (0.9 * dense_score + 0.1 * rank_score) * status_weight + applicability_delta
                )
                metadata["score_source"] = "layered_fusion"
                metadata["retrieval"] = {
                    "layer": layer,
                    "rank": rank,
                    "dense_score": round(dense_score, 6),
                    "rrf_score": round(rank_score, 6),
                    "status_weight": status_weight,
                    "applicability_adjustment": round(applicability_delta, 6),
                    "applicability_matches": applicability_matches,
                    "final_score": round(fused_score, 6),
                }
                item["metadata"] = metadata
                item["score"] = fused_score
                ranked.append(item)

        ranked.sort(key=lambda item: _safe_score(item.get("score")), reverse=True)
        min_score = self._min_score
        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        seen_lineage: set[str] = set()
        merged: list[dict[str, Any]] = []
        candidate_count = 0

        def _selection_tier(item: Any) -> int:
            """The access order for lineage dedup; this order is sensitive.

            Raw facts are concrete and usually score higher than the crystallization summarizing them,
            so a pure score order would let evidence crowd out its own summary -- and when a run
            crystallizes all pending facts (the common case), this would empty the crystallization layer
            entirely. Therefore mature crystals come first. Unsubstantiated candidates are deliberately
            last: before any boost, they must not displace the evidence they derive from.
            """
            metadata = item.get("metadata") or {}
            metadata = metadata if isinstance(metadata, dict) else {}
            if metadata.get("layer") != "crystallized":
                return 1
            return 2 if str(metadata.get("status") or "") == "candidate" else 0

        for item in sorted(ranked, key=_selection_tier):
            memory_id = str(item.get("id") or "")
            metadata = item.get("metadata") or {}
            metadata = metadata if isinstance(metadata, dict) else {}
            score = _safe_score(item.get("score"))
            if min_score is not None and score < min_score:
                dropped.append({"id": memory_id, "reason": "below_min_score"})
                continue
            status = str(metadata.get("status") or "")
            if status == "candidate" and candidate_count >= _MAX_CANDIDATE_RESULTS:
                dropped.append({"id": memory_id, "reason": "candidate_quota"})
                continue
            text_key = _normalized_text(item.get("memory") or item.get("text") or item.get("data"))
            is_crystal = metadata.get("layer") == "crystallized"
            lineage_ids = {memory_id} if memory_id else set()
            if is_crystal:
                lineage_ids.update(_string_list(metadata.get("source_ids")))
            if memory_id and memory_id in seen_ids:
                dropped.append({"id": memory_id, "reason": "duplicate_id"})
                continue
            if text_key and text_key in seen_texts:
                dropped.append({"id": memory_id, "reason": "duplicate_text"})
                continue
            # Lineage suppression is deliberately asymmetric. Two crystals referencing the same evidence
            # are near-duplicates, so keep the weaker one. However, a raw record is not made redundant
            # merely because a crystal references it: dropping it would leave the caller with only a
            # summary and no verifiable evidence, and the raw layer is also the safe fallback.
            if is_crystal and lineage_ids.intersection(seen_lineage):
                dropped.append({"id": memory_id, "reason": "lineage_overlap"})
                continue
            merged.append(item)
            if memory_id:
                seen_ids.add(memory_id)
            if text_key:
                seen_texts.add(text_key)
            seen_lineage.update(lineage_ids)
            candidate_count += int(status == "candidate")

        if len(merged) < request.limit:
            remaining = request.limit - len(merged)
            max_provenance_lookups = self._provenance_lookup_limit
            crystals_by_score = sorted(
                [
                    item
                    for item in merged
                    if isinstance(item, dict)
                    and (item.get("metadata") or {}).get("layer") == "crystallized"
                    and (item.get("metadata") or {}).get("status", "active")
                    in {"active", "canonical"}
                ],
                key=lambda item: _safe_score(item.get("score")),
                reverse=True,
            )
            # Build an ordered query plan first. When multiple crystals reference the same source,
            # the first/highest-scoring crystal owns the attribution.
            lookup_plan: list[tuple[str, dict[str, Any], int, int]] = []
            planned_ids: set[str] = set()
            for crystal in crystals_by_score:
                if len(lookup_plan) >= max_provenance_lookups:
                    break
                meta = crystal.get("metadata", {})
                source_ids = meta.get("source_ids", []) if isinstance(meta, dict) else []
                if not isinstance(source_ids, list):
                    continue
                lookups_for_crystal = 0
                for source_rank, sid in enumerate(source_ids):
                    if (
                        lookups_for_crystal >= self._provenance_per_crystal
                        or len(lookup_plan) >= max_provenance_lookups
                    ):
                        break
                    if not isinstance(sid, str) or sid in seen_ids or sid in planned_ids:
                        continue
                    lookups_for_crystal += 1
                    planned_ids.add(sid)
                    lookup_plan.append((sid, crystal, source_rank, lookups_for_crystal))

            if lookup_plan:
                try:
                    fetched = self._batch_get_memories([item[0] for item in lookup_plan])
                except Exception as exc:
                    logger.warning("批量 provenance 回查失败: %s", exc)
                    fetched = []
                fetched_by_id = {
                    str(item.get("id")): item
                    for item in fetched
                    if isinstance(item, dict) and item.get("id")
                }
                for sid, crystal, source_rank, rank_within_crystal in lookup_plan:
                    if remaining <= 0:
                        break
                    raw = fetched_by_id.get(sid)
                    if not raw or not raw.get("memory"):
                        continue
                    raw = dict(raw)
                    raw_meta = dict(raw.get("metadata") or {})
                    raw_meta.update(
                        {
                            "score_source": "crystal_provenance",
                            "expanded_from_crystal": crystal.get("id"),
                            "expanded_source_rank": source_rank,
                        }
                    )
                    raw["metadata"] = raw_meta
                    parent_score = _safe_score(crystal.get("score"))
                    raw["score"] = parent_score * 0.5 * (0.95 ** (rank_within_crystal - 1))
                    raw_id = str(raw.get("id") or "")
                    raw_text = _normalized_text(raw.get("memory"))
                    if min_score is not None and raw["score"] < min_score:
                        continue
                    if raw_id and raw_id in seen_ids:
                        continue
                    if raw_text and raw_text in seen_texts:
                        continue
                    merged.append(raw)
                    if raw_id:
                        seen_ids.add(raw_id)
                        seen_lineage.add(raw_id)
                    if raw_text:
                        seen_texts.add(raw_text)
                    remaining -= 1

        merged.sort(key=lambda item: _safe_score(item.get("score")), reverse=True)
        report.update(
            {
                "selected": min(len(merged), request.limit),
                "candidate_selected": sum(
                    (item.get("metadata") or {}).get("status") == "candidate"
                    for item in merged[: request.limit]
                ),
                "dropped": dropped[:20],
                "dropped_count": len(dropped),
            }
        )
        return _apply_display_texts({"results": merged[: request.limit], "diagnostics": report})

    def _search_crystal_boost(self, request: SearchRequest) -> dict[str, Any]:
        """Apply weighted boost without bypassing the authoritative crystal read path."""
        results = self._search_layered(request)
        result_list = results.get("results", []) if isinstance(results, dict) else []
        result_list = _normalize_result_scores(result_list)

        for r in result_list:
            meta = r.get("metadata", {})
            if isinstance(meta, dict) and meta.get("layer") == "crystallized":
                r["score"] = min(1.0, _safe_score(r.get("score")) * 1.2)

        result_list = self._apply_min_score_filter_list(result_list)
        result_list.sort(key=lambda x: _safe_score(x.get("score")), reverse=True)
        response = {
            "results": result_list,
            "diagnostics": dict(results.get("diagnostics") or {}),
        }
        response["diagnostics"]["strategy"] = "crystal_boost"
        return _apply_display_texts(response)

    def _apply_min_score_filter(self, result: Any) -> Any:
        """Filter results below min_score. Works for dict-with-results or list formats."""
        if self._min_score is None:
            return result
        if isinstance(result, dict) and isinstance(result.get("results"), list):
            result = dict(result)
            result["results"] = self._apply_min_score_filter_list(result["results"])
        elif isinstance(result, list):
            result = self._apply_min_score_filter_list(result)
        return result

    def _apply_min_score_filter_list(self, items: list) -> list:
        """Remove entries whose score is below the configured min_score."""
        if self._min_score is None:
            return items
        return [
            item
            for item in items
            if not isinstance(item, dict) or _safe_score(item.get("score")) >= self._min_score
        ]

    def get_memories(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> Any:
        """List all memories under the specified scope; at least one scope parameter is required."""
        self.ensure_ready()
        filters = build_scope_filters(user_id=user_id, agent_id=agent_id, run_id=run_id)
        if not filters:
            raise MissingMemoryScopeError("至少需要提供 user_id、agent_id 或 run_id 之一")
        raw_result = self.backend.get_memories(filters)
        raw_items = (
            list(raw_result.get("results", []))
            if isinstance(raw_result, dict)
            else list(raw_result or [])
        )
        crystals = (
            self.solidification.current_crystals(user_id=user_id, agent_id=agent_id, run_id=run_id)
            if self.solidification is not None
            else []
        )
        return _apply_display_texts({"results": [*raw_items, *crystals]})

    def get_memory(self, memory_id: str) -> Any:
        """Read a single memory by ID."""
        self.ensure_ready()
        if self.solidification is not None:
            crystal = self.solidification.get_crystal(memory_id)
            if crystal is not None:
                return _apply_display_text(crystal)
        return _apply_display_text(self.backend.get_memory(memory_id))

    def update_memory(self, memory_id: str, data: str) -> Any:
        """Update the content of a single memory."""
        self.ensure_ready()
        if self.solidification is not None and self.solidification.get_crystal(memory_id):
            raise MemoryServiceError(
                "crystals are immutable ledger assets; retract, rollback, or re-crystallize instead"
            )
        case_ids: list[str] = []
        if self.solidification is not None:
            old_record = self.backend.get_memory(memory_id)
            case_ids = self.solidification.prepare_source_update(memory_id, data, old_record)
        try:
            result = self.backend.update_memory(memory_id, data=data)
        except Exception:
            if case_ids:
                try:
                    self.solidification.compensate_source_update(
                        case_ids, "raw backend update failed; restored prior validity"
                    )
                except Exception:
                    logger.critical(
                        "raw update compensation failed; disputed heads remain isolated",
                        exc_info=True,
                    )
            raise
        if case_ids:
            try:
                updated = self.backend.get_memory(memory_id)
                self.solidification.complete_source_update(case_ids, memory_id, updated)
            except Exception:
                # The raw update is already committed. Leaving its dependants pending is a safe,
                # recoverable state; never revive stale crystal recalls.
                logger.critical(
                    "raw update evidence finalization failed; dependants remain disputed",
                    exc_info=True,
                )
        return result

    def delete_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Delete a raw memory, or logically retract a crystal.

        The ledger transformation happens first. If it fails, the backend delete is not attempted,
        which prevents a deleted source from leaving still-valid derived claims behind.
        """
        self.ensure_ready()
        if self.solidification is None:
            if memory_id.startswith("cr_"):
                raise MemoryServiceError("stable crystal deletion requires solidification")
            self.backend.delete_memory(memory_id)
            return None

        report = self.solidification.retract_for_delete(memory_id)
        if report.get("kind") == "raw_source":
            self.backend.delete_memory(memory_id)
            self.solidification.verification_source_deleted(
                memory_id, report.get("affected_crystal_ids") or []
            )
        return report

    def delete_all_memories(
        self,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Delete all memories under the specified scope; at least one scope parameter is required."""
        self.ensure_ready()
        filters = build_scope_filters(user_id=user_id, agent_id=agent_id, run_id=run_id)
        if not filters:
            raise MissingMemoryScopeError("至少需要提供 user_id、agent_id 或 run_id 之一")
        report = None
        if self.solidification is not None:
            # Retract derived knowledge before removing its raw evidence.
            report = self.solidification.retract_scope(filters)
        self.backend.delete_all_memories(filters)

        if self.crystallizer is not None and user_id:
            self.crystallizer.clear_user_state(user_id)
        return report

    def memory_history(self, memory_id: str) -> Any:
        """Read the change history of a single memory."""
        self.ensure_ready()
        if self.solidification is not None:
            revisions = self.solidification.history(memory_id)
            if revisions:
                return {"crystal_id": memory_id, "revisions": revisions}
        return self.backend.memory_history(memory_id)

    def reset_all(self) -> None:
        """Clear all memories (for development/debugging only)."""
        self.ensure_ready()
        self.reset_factory()

    def reset_factory(self) -> dict[str, Any]:
        """Factory-level full reset: vector store + history DB + crystallizer state + audit log.

        After the reset, the system returns to its blank first-start state. Returns a per-component
        reset summary.
        """
        self.ensure_ready()
        summary: dict[str, Any] = {}

        # 1. Clear the vector store + history DB (mem0 reset internally drops and recreates the history table)
        self.backend.reset_all()
        summary["vector_store"] = "reset"
        summary["history_db"] = "reset"

        # 2. Reset the crystallizer (in-memory state + state file + audit log)
        if self.crystallizer is not None:
            crystal_summary = self.crystallizer.reset_all_state()
            summary["crystallizer"] = crystal_summary
        else:
            summary["crystallizer"] = "not enabled"

        # 3. Clear the solidification ledger (from phase two onward, also add the crystals collection and doc repo)
        if self.solidification is not None:
            try:
                summary["solidification"] = self.solidification.reset_all_state()
            except Exception as exc:
                logger.error("工厂重置: 账本清空失败: %s", exc)
                summary["solidification"] = {"error": str(exc)}
        else:
            summary["solidification"] = "not enabled"

        logger.info("工厂重置完成: %s", summary)
        return summary

    def solidification_state(self) -> dict[str, Any]:
        """Return the watermark marks for ledger integrity and derived projections."""
        if self.solidification is None:
            return {"enabled": False}
        return self.solidification.state()

    def verification_state(self) -> dict[str, Any]:
        if self.solidification is not None:
            state = self.solidification.verification_state()
            if self._validity_config.get("requested") and not state.get("effective"):
                return {
                    **state,
                    "requested": True,
                    "reason": state.get("reason") or "disabled",
                }
            return state
        requested = bool(self._validity_config.get("requested"))
        return {
            "requested": requested,
            "effective": False,
            "reason": "crystallization_disabled" if requested else "disabled",
        }

    def _ensure_validity(self) -> None:
        if self.solidification is None or not getattr(
            self.solidification, "validity_enabled", False
        ):
            raise MemoryNotReadyError("validity dependency is disabled")

    def verification_cases(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._ensure_validity()
        scope = self._verification_scope(user_id, agent_id, run_id)
        cases = self.solidification.verification_cases(state=state, scope=scope, limit=limit)
        return {"cases": cases, "total": len(cases)}

    @staticmethod
    def _verification_scope(
        user_id: str | None, agent_id: str | None, run_id: str | None
    ) -> dict[str, str]:
        scope = build_scope_filters(user_id=user_id, agent_id=agent_id, run_id=run_id)
        if not scope:
            raise MissingMemoryScopeError("verification requires user_id, agent_id, or run_id")
        return scope

    def verification_case(
        self,
        case_id: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_validity()
        scope = self._verification_scope(user_id, agent_id, run_id)
        case = self.solidification.verification_case(case_id)
        case_scope = (case or {}).get("scope") or {}
        if case is None or not all(case_scope.get(key) == value for key, value in scope.items()):
            raise MemoryServiceError(f"verification case not found: {case_id}")
        return case

    def verification_scan(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_validity()
        scope = self._verification_scope(user_id, agent_id, run_id)
        return self.solidification.verification_scan(scope=scope)

    def verification_retry(
        self,
        case_id: str,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.verification_case(case_id, user_id=user_id, agent_id=agent_id, run_id=run_id)
        return self.solidification.verification_retry(case_id)

    def verification_resolve(
        self,
        case_id: str,
        decision: dict[str, Any],
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        self.verification_case(case_id, user_id=user_id, agent_id=agent_id, run_id=run_id)
        return self.solidification.commit_verification_decision(case_id, decision, actor="user")

    def solidification_preflight(self) -> dict[str, Any]:
        if self.solidification is None:
            return {
                "ok": False,
                "authority": "ledger",
                "error": "solidification is not enabled",
            }
        return self.solidification.preflight()

    def crystal_history(self, crystal_id: str) -> dict[str, Any]:
        """Read the full revision chain of a crystal.

        Accepts only a stable ledger crystal_id.
        """
        if self.solidification is None:
            return {"enabled": False, "revisions": []}
        resolved = crystal_id
        revisions = self.solidification.history(resolved)
        return {
            "enabled": True,
            "crystal_id": resolved,
            "requested_id": crystal_id,
            "revisions": revisions,
            "total": len(revisions),
        }

    def crystals_as_of(
        self,
        *,
        as_of: str | None = None,
        user_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        """Read the historical head pointer without changing the current head pointer."""
        if self.solidification is None:
            return {"enabled": False, "crystals": [], "total": 0}
        rev_id: int | None = None
        timestamp: str | None = None
        if as_of:
            value = str(as_of).strip()
            if value.isdigit():
                rev_id = int(value)
            else:
                timestamp = self._parse_utc_datetime(value).isoformat()
        revisions = self.solidification.crystals_as_of(
            rev_id=rev_id,
            timestamp=timestamp,
            user_id=user_id,
            statuses=tuple(statuses) if statuses else None,
        )
        return {
            "enabled": True,
            "as_of": rev_id if rev_id is not None else timestamp,
            "user_id": user_id,
            "statuses": statuses or [],
            "crystals": revisions,
            "total": len(revisions),
        }

    def crystal_maturity(self, crystal_id: str) -> dict[str, Any]:
        if self.solidification is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "maturity": self.solidification.maturity(crystal_id),
        }

    def crystal_card(self, crystal_id: str) -> dict[str, Any]:
        """Return the canonical Markdown card for a stable ledger crystal ID."""
        if self.solidification is None:
            return {"enabled": False}
        if not getattr(self.solidification, "document_projection_enabled", False):
            return {"enabled": False, "reason": "document_projection_disabled"}
        card = self.solidification.card(crystal_id)
        if card is None:
            raise MemoryServiceError(f"canonical crystal card not found: {crystal_id}")
        return {"enabled": True, "requested_id": crystal_id, **card}

    def solidification_graph(
        self,
        subject: str,
        *,
        max_depth: int = 2,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if self.solidification is None:
            return {"enabled": False, "edges": [], "total": 0}
        if not getattr(self.solidification, "graph_projection_enabled", False):
            return {
                "enabled": False,
                "reason": "graph_projection_disabled",
                "edges": [],
                "total": 0,
            }
        return {
            "enabled": True,
            **self.solidification.graph_traverse(subject, max_depth=max_depth, user_id=user_id),
        }

    def solidification_graph_conflicts(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if self.solidification is None:
            return {"enabled": False, "conflicts": [], "total": 0}
        if not getattr(self.solidification, "graph_projection_enabled", False):
            return {
                "enabled": False,
                "reason": "graph_projection_disabled",
                "conflicts": [],
                "total": 0,
            }
        return {
            "enabled": True,
            **self.solidification.graph_conflicts(
                subject=subject, predicate=predicate, user_id=user_id
            ),
        }

    def solidification_rebuild(self, projections: list[str]) -> dict[str, Any]:
        """Rebuild the derived projections from the immutable SQLite ledger."""
        if self.solidification is None:
            return {"enabled": False, "projections": {}}
        return {
            "enabled": True,
            "projections": self.solidification.rebuild_projections(projections),
        }

    def solidification_evaluate_maturity(
        self,
        *,
        crystal_ids: list[str] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        if self.solidification is None:
            return {"enabled": False}
        clock = self._parse_utc_datetime(now) if now else None
        return self.solidification.evaluate_maturity(
            crystal_ids=crystal_ids or None,
            now=clock,
        )

    def solidification_rollback(
        self,
        *,
        crystal_id: str | None = None,
        version: int | None = None,
        rev_id: int | None = None,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Move the ledger head pointer and immediately reconcile the vector projection."""
        if self.solidification is None:
            return {"enabled": False}
        if batch_id:
            return {"enabled": True, **self.solidification.rollback_batch(batch_id)}
        if not crystal_id:
            raise MemoryServiceError("crystal_id is required for item rollback")
        return {
            "enabled": True,
            **self.solidification.rollback_crystal(crystal_id, version=version, rev_id=rev_id),
        }

    @staticmethod
    def _parse_utc_datetime(value: str) -> datetime:
        text = str(value or "").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MemoryServiceError(f"invalid ISO-8601 timestamp: {value}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def health(self) -> dict[str, Any]:
        """Return a summary of the backend health status."""
        result: dict[str, Any] = dict(self.backend.health())
        if self.solidification is not None:
            result["solidification"] = self.solidification.preflight()
        return result

    def ensure_ready(self) -> None:
        """Raise MemoryNotReadyError if the backend has not been initialized."""
        if not self.ready:
            raise MemoryNotReadyError("记忆尚未初始化")
