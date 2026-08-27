"""FastAPI transport layer -- maps HTTP requests to MemoryService business calls.

This module is responsible only for route definitions and exception-to-HTTP status mapping. All
business logic is handled by MemoryService (service.py), so switching to another transport such as
MCP requires no changes to any business code.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import Field, model_validator
from clawcodex_ext.latent_memory.server.config import (
    load_config,
    load_crystallization_config,
    load_salience_gate_config,
    load_solidification_config,
    load_validity_config,
)
from clawcodex_ext.latent_memory.server.lib.salience_gate import SalienceGate
from clawcodex_ext.latent_memory.server.schemas import (
    AddRequest,
    SanitizedRequest,
    SearchRequest,
    UpdateRequest,
    sanitize_request_strings,
)
from clawcodex_ext.latent_memory.server.service import (
    MemoryNotReadyError,
    MemoryService,
    MissingMemoryScopeError,
)
from clawcodex_ext.latent_memory.server.token_usage import token_usage_tracker

logger = logging.getLogger("memory-server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

config = load_config()
gate_config = load_salience_gate_config()
crystal_config = load_crystallization_config()
solidify_config = load_solidification_config()
validity_config = load_validity_config()
# The solidification and crystallization layers are merged into a single switch;
# SOLIDIFY_ENABLED is no longer exposed separately.
solidify_config["enabled"] = crystal_config["enabled"]
validity_config["effective"] = bool(validity_config["requested"] and crystal_config["enabled"])
if validity_config["requested"] and not validity_config["effective"]:
    logger.warning("有效性验证已请求但 CRYSTALLIZE_ENABLED=false；无 Ledger，自动降级为关闭")
salience_gate = SalienceGate.from_config(gate_config)
memory_service = MemoryService(
    config,
    salience_gate=salience_gate,
    default_search_strategy=crystal_config["search_strategy"],
    min_score=crystal_config["min_score"],
    search_workers=solidify_config["search_workers"],
    raw_search_timeout_seconds=solidify_config["raw_search_timeout_seconds"],
    crystal_search_timeout_seconds=solidify_config["crystal_search_timeout_seconds"],
    crystal_candidate_limit=solidify_config["crystal_candidate_limit"],
    provenance_lookup_limit=solidify_config["provenance_lookup_limit"],
    provenance_per_crystal=solidify_config["provenance_per_crystal"],
    validity_config=validity_config,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the backend on startup, release resources on shutdown."""
    memory_service.start()

    embed_fn = None
    validity_llm_fn = None
    crystallizer_llm_fn = None
    provider = ""
    llm_model = ""
    if crystal_config["enabled"]:
        try:
            from clawcodex_ext.latent_memory.server.lib.crystallization.clients import (
                build_embed_fn_from_config,
            )

            embed_fn = build_embed_fn_from_config(config)
        except Exception:
            memory_service.stop()
            raise

        from clawcodex_ext.latent_memory.server.lib.semantic_crystallizer import llm_call

        provider = crystal_config["llm_provider"]
        if provider == "openai":
            llm_base_url = crystal_config["openai_base_url"]
            llm_model = crystal_config["openai_model"]
            llm_api_key = crystal_config["openai_api_key"]
        else:
            llm_base_url = crystal_config["ollama_base_url"]
            llm_model = crystal_config["ollama_model"]
            llm_api_key = ""
        validity_config["model_id"] = f"{provider}/{llm_model}"

        def crystallizer_llm_fn(sys: str, usr: str, schema: dict[str, Any]) -> dict[str, Any]:
            return llm_call(
                sys,
                usr,
                schema,
                llm_base_url,
                llm_model,
                provider,
                llm_api_key,
                enable_thinking=crystal_config.get("llm_enable_thinking"),
            )

        def validity_llm_fn(sys: str, usr: str, schema: dict[str, Any]) -> dict[str, Any]:
            return llm_call(
                sys,
                usr,
                schema,
                llm_base_url,
                llm_model,
                provider,
                llm_api_key,
                max_retries=1,
                timeout=validity_config["llm_timeout_seconds"],
                enable_thinking=crystal_config.get("llm_enable_thinking"),
            )

    # Ledger is the single source of truth for crystallization; all other crystal stores are
    # derived projections of it.
    # It starts together with the crystallizer.
    # Ledger startup failure is fatal.
    solidification = None
    if solidify_config["enabled"]:
        try:
            from clawcodex_ext.latent_memory.server.lib.solidification import SolidificationStore

            solidification = SolidificationStore(
                solidify_config,
                embed_fn=embed_fn,
                memory_config=config,
            )
            memory_service.solidification = solidification
            if validity_config["effective"]:
                solidification.enable_validity(
                    validity_config,
                    backend_accessor=lambda: memory_service.backend,
                    llm_fn=validity_llm_fn,
                )
            preflight = solidification.preflight()
            if not preflight["ok"]:
                raise RuntimeError(f"solidification preflight failed: {preflight}")
            logger.info(
                "持久固化层已启用: authority=ledger, db=%s, vector_projection=%s",
                solidify_config["db_path"],
                solidification.vector_projection_enabled,
            )
        except Exception:
            logger.critical("authoritative solidification ledger failed to start", exc_info=True)
            memory_service.stop()
            raise

    if crystal_config["enabled"]:
        from clawcodex_ext.latent_memory.server.lib.semantic_crystallizer import (
            SemanticCrystallizer,
        )

        backend = memory_service.backend
        if embed_fn is None:
            memory_service.stop()
            raise RuntimeError("结晶器 embedding 未初始化")

        try:
            crystallizer = SemanticCrystallizer(
                backend_accessor=lambda: backend,
                embed_fn=embed_fn,
                llm_fn=crystallizer_llm_fn,
                config=crystal_config,
                solidification=solidification,
            )
        except Exception:
            memory_service.stop()
            raise
        memory_service.crystallizer = crystallizer
        logger.info(
            "语义结晶器已启用: threshold=%d, interval=%gh, strategy=%s, llm=%s/%s",
            crystal_config["threshold"],
            crystal_config["interval_hours"],
            crystal_config["search_strategy"],
            provider,
            llm_model,
        )

    try:
        yield
    finally:
        memory_service.stop()


app = FastAPI(
    title="本地记忆服务",
    description="由 Qdrant 支撑的 Mem0 兼容记忆服务",
    lifespan=lifespan,
)


def call_service(action: Callable[[], Any], *, not_found: bool = False) -> Any:
    """Unified service-call wrapper that maps MemoryService layer exceptions to HTTPException.

    Args:
        action: the no-arg callable to execute, usually a lambda or closure.
        not_found: if True, unknown exceptions map to 404; otherwise map to 500.
    """
    try:
        return action()
    except MemoryNotReadyError as exc:
        raise HTTPException(503, str(exc)) from exc
    except MissingMemoryScopeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("记忆服务调用失败")
        status_code = 404 if not_found else 500
        raise HTTPException(status_code, str(exc)) from exc


def _validate_memory_id(memory_id: str) -> None:
    """Validate that memory_id is a legal UUID; an invalid one 404s directly to avoid hitting
    Qdrant and triggering a 500.

    Qdrant point IDs only accept unsigned integers or UUIDs. All IDs the memory service actually
    writes are UUID format (generated by mem0), so a non-UUID ID is guaranteed not to exist.
    """
    try:
        uuid.UUID(memory_id)
    except (ValueError, AttributeError):
        raise HTTPException(404, f"记忆不存在：{memory_id}")


def _validate_deletable_id(memory_id: str) -> None:
    """Delete routes accept both mem0 UUIDs and stable ledger crystal IDs."""
    if re.fullmatch(r"cr_[0-9a-fA-F]{32}", memory_id):
        return
    _validate_memory_id(memory_id)


@app.post("/memories")
def add_memories(request: AddRequest):
    return call_service(lambda: memory_service.add_memories(request))


@app.post("/search")
def search_memories(request: SearchRequest):
    return call_service(lambda: memory_service.search_memories(request))


@app.get("/memories")
def get_memories(
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    user_id = sanitize_request_strings(user_id)
    agent_id = sanitize_request_strings(agent_id)
    run_id = sanitize_request_strings(run_id)
    return call_service(
        lambda: memory_service.get_memories(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
        )
    )


@app.get("/memories/{memory_id}")
def get_memory(memory_id: str):
    memory_id = sanitize_request_strings(memory_id)
    _validate_memory_id(memory_id)
    return call_service(lambda: memory_service.get_memory(memory_id), not_found=True)


@app.put("/memories/{memory_id}")
def update_memory(memory_id: str, request: UpdateRequest):
    memory_id = sanitize_request_strings(memory_id)
    _validate_memory_id(memory_id)
    return call_service(lambda: memory_service.update_memory(memory_id, request.data))


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    memory_id = sanitize_request_strings(memory_id)
    _validate_deletable_id(memory_id)

    def action() -> dict[str, str]:
        memory_service.delete_memory(memory_id)
        return {"message": "Memory deleted successfully"}

    return call_service(action)


@app.delete("/memories")
def delete_all_memories(
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    user_id = sanitize_request_strings(user_id)
    agent_id = sanitize_request_strings(agent_id)
    run_id = sanitize_request_strings(run_id)

    def action() -> dict[str, str]:
        memory_service.delete_all_memories(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
        )
        return {"message": "All memories deleted successfully"}

    return call_service(action)


@app.get("/memories/{memory_id}/history")
def memory_history(memory_id: str):
    memory_id = sanitize_request_strings(memory_id)
    _validate_memory_id(memory_id)
    return call_service(lambda: memory_service.memory_history(memory_id))


@app.post("/reset")
def reset_all():
    def action() -> dict[str, str]:
        memory_service.reset_all()
        return {"message": "All memories reset successfully"}

    return call_service(action)


@app.post("/reset/factory")
def reset_factory():
    """Factory-level full wipe: vector store + history DB + crystallizer state + audit logs.

    After clearing, the system returns to its blank first-start state. For dev/evaluation only.
    """

    def action() -> dict[str, Any]:
        summary = memory_service.reset_factory()
        return {"message": "Factory reset completed", "details": summary}

    return call_service(action)


@app.get("/health")
def health():
    return memory_service.health()


@app.post("/crystallize")
def trigger_crystallization(
    user_id: str = Query(...),
    force: bool = Query(False),
):
    """Manually trigger crystallization. With force=True, the time gate and fact-count gate are skipped."""
    user_id = sanitize_request_strings(user_id)

    def action() -> dict[str, Any]:
        crystallizer = memory_service.crystallizer
        if crystallizer is None:
            return {"enabled": False, "message": "Crystallizer is not enabled"}
        if force:
            triggered = crystallizer.force_crystallize(user_id)
        else:
            triggered = crystallizer._check_gates(user_id)
        return {
            "enabled": True,
            "triggered": triggered,
            "pending": len(crystallizer.state.pending_ids),
        }

    return call_service(action)


@app.get("/crystallize/status")
def crystallization_status():
    """Return the current crystallizer state."""

    def action() -> dict[str, Any]:
        crystallizer = memory_service.crystallizer
        if crystallizer is None:
            return {"enabled": False}
        state = crystallizer.state
        pending_by_user = {uid: len(ids) for uid, ids in state.pending_ids.items() if ids}
        return {
            "enabled": True,
            "last_run": state.last_run,
            "pending_count": sum(pending_by_user.values()),
            "pending_by_user": pending_by_user,
            "total_created": state.total_created,
            "total_absorbed": state.total_absorbed,
            "total_failed": state.total_failed,
            "total_rejected": state.total_rejected,
            "total_evicted": state.total_evicted,
            "tracked_fact_attempts": len(state.fact_attempts),
            "total_operations": state.total_operations,
            "running": state.running,
        }

    return call_service(action)


@app.get("/crystallize/audit")
def crystallization_audit(
    limit: int = Query(10, ge=1, le=100),
):
    """Return the most recent audit records (last N entries of the JSONL file)."""

    def action() -> dict[str, Any]:
        crystallizer = memory_service.crystallizer
        if crystallizer is None:
            return {"enabled": False, "records": []}
        audit_path = crystallizer._audit_path
        from pathlib import Path

        p = Path(audit_path)
        if not p.exists():
            return {"enabled": True, "records": [], "total": 0}
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines[-limit:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"enabled": True, "records": records, "total": len(lines)}

    return call_service(action)


@app.post("/crystallize/reset")
def reset_crystallization(user_id: str = Query(...)):
    """Reset the specified user's crystallization state (clear pending_ids and time-gate cache)."""
    user_id = sanitize_request_strings(user_id)

    def action() -> dict[str, Any]:
        crystallizer = memory_service.crystallizer
        if crystallizer is None:
            return {"enabled": False, "message": "Crystallizer is not enabled"}
        pending_count = crystallizer.clear_user_state(user_id)
        return {
            "enabled": True,
            "user_id": user_id,
            "cleared_pending": pending_count,
        }

    return call_service(action)


@app.get("/solidify/state")
def solidification_state():
    """Return authoritative ledger integrity and derived projection state."""
    return call_service(lambda: memory_service.solidification_state())


@app.get("/crystals")
def crystals_as_of(
    as_of: str | None = Query(None, description="全局 rev_id 或 ISO-8601 时间；省略时读取当前时点"),
    user_id: str | None = Query(None),
    status: list[str] | None = Query(None, description="可重复传入的状态过滤器"),
):
    """Time-travel read of each crystal's head at the given point; does not modify the current version."""
    return call_service(
        lambda: memory_service.crystals_as_of(
            as_of=sanitize_request_strings(as_of),
            user_id=sanitize_request_strings(user_id),
            statuses=sanitize_request_strings(status),
        )
    )


@app.get("/crystals/{crystal_id}/history")
def crystal_history(crystal_id: str):
    """Return a crystal's full revision chain. Accepts a crystal_id or a mem0 memory_id."""
    crystal_id = sanitize_request_strings(crystal_id)
    return call_service(lambda: memory_service.crystal_history(crystal_id), not_found=True)


@app.get("/crystals/{crystal_id}/maturity")
def crystal_maturity(crystal_id: str):
    """Return reinforcement, run, conflict, and survival-time metrics replayed from the current parent chain."""
    crystal_id = sanitize_request_strings(crystal_id)
    return call_service(lambda: memory_service.crystal_maturity(crystal_id), not_found=True)


@app.get("/crystals/{crystal_id}/card")
def crystal_card(crystal_id: str):
    """Return the deterministic Markdown card for the canonical head."""
    crystal_id = sanitize_request_strings(crystal_id)
    return call_service(lambda: memory_service.crystal_card(crystal_id), not_found=True)


@app.delete("/crystals/{crystal_id}")
def delete_crystal(crystal_id: str):
    """Logically retract a crystal and remove its derived vector projection."""
    crystal_id = sanitize_request_strings(crystal_id)

    def action() -> dict[str, Any]:
        report = memory_service.delete_memory(crystal_id)
        return {"message": "Crystal retracted successfully", "solidification": report}

    return call_service(action, not_found=True)


class SolidifyRollbackRequest(SanitizedRequest):
    """Either a batch selector, or exactly one item-version selector."""

    batch_id: str | None = None
    crystal_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    rev_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_selector(self) -> "SolidifyRollbackRequest":
        if self.batch_id:
            if self.crystal_id or self.version is not None or self.rev_id is not None:
                raise ValueError("batch_id cannot be combined with an item selector")
            return self
        if not self.crystal_id:
            raise ValueError("crystal_id or batch_id is required")
        if (self.version is None) == (self.rev_id is None):
            raise ValueError("exactly one of version and rev_id is required")
        return self


class SolidifyMaturityRequest(SanitizedRequest):
    crystal_ids: list[str] | None = None


class SolidifyRebuildRequest(SanitizedRequest):
    projections: list[str] = Field(default_factory=list)


class ValidityResolveRequest(SanitizedRequest):
    decision: str = Field(
        pattern="^(confirm_left|confirm_right|coexist|repair|insufficient_evidence)$"
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    validity: dict[str, Any] = Field(default_factory=dict)
    repair: dict[str, Any] | None = None


@app.post("/solidify/rollback")
def solidification_rollback(req: SolidifyRollbackRequest):
    """Move the head by a single version or a whole crystal batch, then immediately reconcile the vector projection."""
    return call_service(
        lambda: memory_service.solidification_rollback(
            crystal_id=req.crystal_id,
            version=req.version,
            rev_id=req.rev_id,
            batch_id=req.batch_id,
        ),
        not_found=True,
    )


@app.post("/solidify/maturity/evaluate")
def solidification_evaluate_maturity(req: SolidifyMaturityRequest):
    """Mechanically scan maturity and expiration criteria; when crystal_ids is omitted, scan all heads."""
    return call_service(
        lambda: memory_service.solidification_evaluate_maturity(crystal_ids=req.crystal_ids)
    )


@app.get("/solidify/graph/conflicts")
def solidification_graph_conflicts(
    subject: str | None = Query(None),
    predicate: str | None = Query(None),
    user_id: str | None = Query(None),
):
    """Filter mechanical conflict candidates with the same subject-predicate, different objects, and overlapping validity."""
    return call_service(
        lambda: memory_service.solidification_graph_conflicts(
            subject=sanitize_request_strings(subject),
            predicate=sanitize_request_strings(predicate),
            user_id=sanitize_request_strings(user_id),
        )
    )


@app.get("/solidify/graph")
def solidification_graph(
    subject: str = Query(..., min_length=1),
    max_depth: int = Query(2, ge=1, le=5),
    user_id: str | None = Query(None),
):
    """Traverse outgoing edges up to five hops starting from the current active/canonical heads."""
    return call_service(
        lambda: memory_service.solidification_graph(
            sanitize_request_strings(subject),
            max_depth=max_depth,
            user_id=sanitize_request_strings(user_id),
        )
    )


@app.post("/solidify/rebuild")
def solidification_rebuild(req: SolidifyRebuildRequest):
    """Rebuild the specified derived projections from the SQLite ledger; an empty list means all projections."""
    return call_service(lambda: memory_service.solidification_rebuild(req.projections))


@app.get("/solidify/preflight")
def solidification_preflight():
    """Check ledger integrity and report the readiness of derived projections."""
    return call_service(lambda: memory_service.solidification_preflight())


@app.get("/solidify/verification/state")
def verification_state():
    """Return verifier backlog, cursor, worker processes, and dependency status."""
    return call_service(lambda: memory_service.verification_state())


@app.get("/solidify/verification/cases")
def verification_cases(
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
    state: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    return call_service(
        lambda: memory_service.verification_cases(
            user_id=sanitize_request_strings(user_id),
            agent_id=sanitize_request_strings(agent_id),
            run_id=sanitize_request_strings(run_id),
            state=sanitize_request_strings(state),
            limit=limit,
        )
    )


@app.get("/solidify/verification/cases/{case_id}")
def verification_case(
    case_id: str,
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    return call_service(
        lambda: memory_service.verification_case(
            sanitize_request_strings(case_id),
            user_id=sanitize_request_strings(user_id),
            agent_id=sanitize_request_strings(agent_id),
            run_id=sanitize_request_strings(run_id),
        ),
        not_found=True,
    )


@app.post("/solidify/verification/scan")
def verification_scan(
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    return call_service(
        lambda: memory_service.verification_scan(
            user_id=sanitize_request_strings(user_id),
            agent_id=sanitize_request_strings(agent_id),
            run_id=sanitize_request_strings(run_id),
        )
    )


@app.post("/solidify/verification/cases/{case_id}/retry")
def verification_retry(
    case_id: str,
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    return call_service(
        lambda: memory_service.verification_retry(
            sanitize_request_strings(case_id),
            user_id=sanitize_request_strings(user_id),
            agent_id=sanitize_request_strings(agent_id),
            run_id=sanitize_request_strings(run_id),
        ),
        not_found=True,
    )


@app.post("/solidify/verification/cases/{case_id}/resolve")
def verification_resolve(
    case_id: str,
    request: ValidityResolveRequest,
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    run_id: str | None = Query(None),
):
    return call_service(
        lambda: memory_service.verification_resolve(
            sanitize_request_strings(case_id),
            request.model_dump(),
            user_id=sanitize_request_strings(user_id),
            agent_id=sanitize_request_strings(agent_id),
            run_id=sanitize_request_strings(run_id),
        ),
        not_found=True,
    )


@app.get("/metrics/token-usage")
def token_usage():
    return token_usage_tracker.snapshot()


@app.post("/metrics/token-usage/reset")
def reset_token_usage(enabled: bool = Query(True)):
    return token_usage_tracker.reset(enabled=enabled)


@app.post("/metrics/token-usage/disable")
def disable_token_usage():
    return token_usage_tracker.disable()


@app.get("/metrics/crystallizer-stats")
def crystallizer_stats():
    """Return the semantic crystallizer's cumulative LLM call and token stats snapshot."""
    crystallizer = memory_service.crystallizer
    if crystallizer is None:
        return {"enabled": False}
    return {"enabled": True, **crystallizer.stats()}


@app.post("/metrics/crystallizer-stats/reset")
def reset_crystallizer_stats():
    """Reset the crystallizer's stats counters, returning the pre-reset snapshot."""
    crystallizer = memory_service.crystallizer
    if crystallizer is None:
        return {"enabled": False}
    return {"enabled": True, **crystallizer.reset_stats()}


class CompositionBatchRequest(SanitizedRequest):
    """Request body for batch-querying the crystal library composition."""

    user_ids: list[str]


@app.get("/metrics/crystallizer-composition")
def crystallizer_composition(user_id: str = Query(..., description="查询的用户 ID")):
    """Return a composition snapshot of the specified user's current crystal knowledge base
    (by asset_type / knowledge_type / version distribution + average confidence + referenced
    source_ids count)."""
    user_id = sanitize_request_strings(user_id)
    crystallizer = memory_service.crystallizer
    if crystallizer is None:
        return {"enabled": False}
    return {"enabled": True, **crystallizer.get_composition(user_id)}


@app.post("/metrics/crystallizer-composition/batch")
def crystallizer_composition_batch(req: CompositionBatchRequest):
    """Aggregate-query the crystal library composition across multiple users (benchmark scenario:
    one user_id per conversation/question)."""
    crystallizer = memory_service.crystallizer
    if crystallizer is None:
        return {"enabled": False}
    return {"enabled": True, **crystallizer.get_composition_aggregated(req.user_ids)}


@app.get("/")
def root():
    return {"message": "Local memory service", "docs": "/docs"}
