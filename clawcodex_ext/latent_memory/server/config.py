from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

logger = logging.getLogger("memory-server")


def memory_state_dir() -> Path:
    """Return the persistent state directory used by the bundled service."""
    configured = os.getenv("CLAWCODEX_MEMORY_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    config_root = Path(
        os.getenv("CLAWCODEX_CONFIG_DIR", str(Path.home() / ".clawcodex"))
    ).expanduser()
    return config_root / "memory"


def configured_mem0_path() -> Path | None:
    configured = os.getenv("MEM0_CONFIG_PATH", "").strip()
    return Path(configured).expanduser() if configured else None


def expand_env_vars(obj: Any) -> Any:
    """Recursively expand ${VAR} references in YAML values."""
    if isinstance(obj, str):
        import re

        def replace(match: re.Match) -> str:
            return os.getenv(match.group(1), match.group(0))

        return re.sub(r"\$\{(\w+)\}", replace, obj)
    if isinstance(obj, dict):
        return {key: expand_env_vars(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(value) for value in obj]
    return obj


def default_history_db_path() -> str:
    """Return the history database path, preferring the environment variable."""
    return os.getenv("HISTORY_DB_PATH", str(memory_state_dir() / "history.db"))


def apply_runtime_overrides(config: dict[str, Any]) -> None:
    """Apply host-local runtime overrides without modifying the shared YAML file."""
    ollama_base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST")
    if ollama_base_url and config.get("embedder", {}).get("provider") == "ollama":
        config.setdefault("embedder", {}).setdefault("config", {})["ollama_base_url"] = (
            ollama_base_url
        )


def build_vector_store_config(config: dict[str, Any]) -> dict[str, Any]:
    """Build a remote or local Qdrant configuration for the bundled service."""
    vector_store_config: dict[str, Any] = {
        "collection_name": os.getenv("COLLECTION_NAME", "memories"),
    }
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_host = os.getenv("QDRANT_HOST", "").strip()
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip()
    if qdrant_url:
        parsed = urlparse(qdrant_url)
        if not parsed.hostname:
            raise ValueError("QDRANT_URL must include a hostname")
        vector_store_config["url"] = qdrant_url
        if qdrant_api_key:
            vector_store_config["api_key"] = qdrant_api_key
    elif qdrant_host:
        vector_store_config.update(
            {"host": qdrant_host, "port": int(os.getenv("QDRANT_PORT", "6333"))}
        )
    else:
        vector_store_config.update(
            {
                "path": os.getenv("QDRANT_PATH", str(memory_state_dir() / "qdrant")),
                "on_disk": True,
            }
        )
    embedding_dims = config.get("embedder", {}).get("config", {}).get("embedding_dims")
    if embedding_dims:
        vector_store_config["embedding_model_dims"] = embedding_dims
    return {"provider": "qdrant", "config": vector_store_config}


def inject_add_retry_config(config: dict[str, Any]) -> None:
    """Inject external exponential backoff retry config from env vars for memory writes
    (mem0 add) that return empty results.

    max_retries=0 means no retry (default). The backoff sequence is
    backoff_base_seconds * (2 ** i), i = 0..max_retries-1.
    """
    config["add_retry"] = {
        "max_retries": int(os.getenv("MEMORY_ADD_RETRY_MAX_RETRIES", "0")),
        "backoff_base_seconds": float(os.getenv("MEMORY_ADD_RETRY_BACKOFF_BASE_SECONDS", "4.0")),
    }


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load Mem0 config from YAML, or build a default config from env vars."""
    path = config_path or configured_mem0_path()
    if path is not None and path.exists():
        logger.info("从 %s 加载配置", path)
        raw = yaml.safe_load(path.read_text())
        config = expand_env_vars(raw)

        config.setdefault("version", "v1.1")
        config.setdefault("history_db_path", default_history_db_path())
        apply_runtime_overrides(config)
        inject_add_retry_config(config)

        if "vector_store" not in config:
            config["vector_store"] = build_vector_store_config(config)

        logger.info(
            "配置: llm=%s/%s, embedder=%s/%s, vector_store=%s",
            config.get("llm", {}).get("provider", "?"),
            config.get("llm", {}).get("config", {}).get("model", "?"),
            config.get("embedder", {}).get("provider", "?"),
            config.get("embedder", {}).get("config", {}).get("model", "?"),
            config.get("vector_store", {}).get("provider", "?"),
        )
        return config

    logger.info("未找到配置文件; 从环境变量构建默认配置")
    llm_provider = os.getenv("LLM_PROVIDER", "openai")
    embedder_provider = os.getenv("EMBEDDER_PROVIDER", "openai")
    llm_config: dict[str, Any] = {
        "model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
        "temperature": 0.1,
    }
    embedder_config: dict[str, Any] = {
        "model": os.getenv("EMBEDDER_MODEL", "text-embedding-3-small"),
    }
    ollama_base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST")
    if ollama_base_url and llm_provider == "ollama":
        llm_config["ollama_base_url"] = ollama_base_url
    if ollama_base_url and embedder_provider == "ollama":
        embedder_config["ollama_base_url"] = ollama_base_url
    embedding_dims = os.getenv("EMBEDDING_DIMS", "").strip()
    if embedding_dims:
        embedder_config["embedding_dims"] = int(embedding_dims)

    provider_config = {
        "llm": {"provider": llm_provider, "config": llm_config},
        "embedder": {"provider": embedder_provider, "config": embedder_config},
    }
    config = {
        "version": "v1.1",
        "vector_store": build_vector_store_config(provider_config),
        **provider_config,
        "history_db_path": default_history_db_path(),
    }
    inject_add_retry_config(config)
    return config


def register_custom_providers() -> None:
    """Register a custom embedder with mem0's EmbedderFactory (currently SageMaker)."""
    from mem0.utils.factory import EmbedderFactory

    EmbedderFactory.provider_to_class["sagemaker"] = (
        "clawcodex_ext.latent_memory.server.sagemaker_embedder.SageMakerEmbedding"
    )


def load_salience_gate_config() -> dict[str, Any]:
    """Load salience gate config from env vars.

    Returns:
        dict with keys: enabled, ollama_model, ollama_base_url

    When ollama_model is set to "none"/"disabled"/"off"/empty string, only Tier 1 is enabled.
    """
    return {
        "enabled": os.getenv("SALIENCE_GATE_ENABLED", "true").lower() == "true",
        "ollama_model": os.getenv("SALIENCE_GATE_OLLAMA_MODEL", "none"),
        "ollama_base_url": os.getenv(
            "SALIENCE_GATE_OLLAMA_BASE_URL",
            os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ),
    }


def _optional_float_env(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


def _optional_bool_env(name: str) -> bool | None:
    """Read a three-state boolean env var: unset returns None, true/1/yes/on returns True,
    false/0/no/off returns False."""
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def _search_strategy_env() -> str:
    value = os.getenv("CRYSTALLIZE_SEARCH_STRATEGY", "layered").strip() or "layered"
    if value not in {"layered", "crystal_boost"}:
        raise ValueError("CRYSTALLIZE_SEARCH_STRATEGY must be layered or crystal_boost")
    return value


def load_crystallization_config() -> dict[str, Any]:
    """Load semantic crystallization config from env vars.

    Returns:
        dict with keys: enabled, threshold, interval_hours, min_cluster_size,
        cluster_create_similarity, cluster_absorb_similarity, cluster_max_size,
        cluster_min_avg_similarity, max_display_chars, llm_provider, ollama_model, ollama_base_url,
        openai_model, openai_base_url, openai_api_key, state_path,
        search_strategy, min_score, quality_filter_enabled,
        max_fact_attempts, min_crystal_confidence
    """
    ollama_base_url = os.getenv(
        "CRYSTALLIZE_OLLAMA_BASE_URL",
        os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    return {
        "enabled": os.getenv("CRYSTALLIZE_ENABLED", "false").lower() == "true",
        "threshold": int(os.getenv("CRYSTALLIZE_THRESHOLD", "50")),
        "interval_hours": float(os.getenv("CRYSTALLIZE_INTERVAL_HOURS", "24")),
        "min_cluster_size": int(os.getenv("CRYSTALLIZE_MIN_CLUSTER_SIZE", "3")),
        "cluster_create_similarity": float(
            os.getenv("CRYSTALLIZE_CLUSTER_CREATE_SIMILARITY", "0.60")
        ),
        "cluster_absorb_similarity": float(
            os.getenv("CRYSTALLIZE_CLUSTER_ABSORB_SIMILARITY", "0.52")
        ),
        "cluster_min_avg_similarity": float(
            os.getenv("CRYSTALLIZE_CLUSTER_MIN_AVG_SIMILARITY", "0.50")
        ),
        "cluster_max_size": int(os.getenv("CRYSTALLIZE_CLUSTER_MAX_SIZE", "30")),
        "max_clusters_per_run": int(os.getenv("CRYSTALLIZE_MAX_CLUSTERS_PER_RUN", "10")),
        "schema_version": int(os.getenv("CRYSTALLIZE_SCHEMA_VERSION", "2")),
        "max_source_ids_per_crystal": int(
            os.getenv("CRYSTALLIZE_MAX_SOURCE_IDS_PER_CRYSTAL", "48")
        ),
        "subject_split_enabled": os.getenv("CRYSTALLIZE_SUBJECT_SPLIT_ENABLED", "true").lower()
        == "true",
        "failure_backoff_minutes": int(os.getenv("CRYSTALLIZE_FAILURE_BACKOFF_MINUTES", "15")),
        "quality_filter_enabled": os.getenv("CRYSTALLIZE_QUALITY_FILTER_ENABLED", "true").lower()
        == "true",
        "max_fact_attempts": int(os.getenv("CRYSTALLIZE_MAX_FACT_ATTEMPTS", "3")),
        "min_crystal_confidence": float(os.getenv("CRYSTALLIZE_MIN_CRYSTAL_CONFIDENCE", "0.65")),
        "max_fact_chars": int(os.getenv("CRYSTALLIZE_MAX_FACT_CHARS", "1200")),
        "max_crystal_chars": int(os.getenv("CRYSTALLIZE_MAX_CRYSTAL_CHARS", "2000")),
        "max_display_chars": int(os.getenv("CRYSTALLIZE_MAX_DISPLAY_CHARS", "420")),
        "embedding_batch_size": max(1, int(os.getenv("CRYSTALLIZE_EMBEDDING_BATCH_SIZE", "32"))),
        "audit_max_bytes": int(os.getenv("CRYSTALLIZE_AUDIT_MAX_BYTES", str(10 * 1024 * 1024))),
        "audit_backups": int(os.getenv("CRYSTALLIZE_AUDIT_BACKUPS", "3")),
        "llm_provider": os.getenv("CRYSTALLIZE_LLM_PROVIDER", "ollama"),
        "ollama_model": os.getenv(
            "CRYSTALLIZE_OLLAMA_MODEL",
            os.getenv("SALIENCE_GATE_OLLAMA_MODEL", "llama3.2:3b"),
        ),
        "ollama_base_url": ollama_base_url,
        "openai_model": os.getenv("CRYSTALLIZE_OPENAI_MODEL", "gpt-4o-mini"),
        "openai_base_url": os.getenv("CRYSTALLIZE_OPENAI_BASE_URL", ""),
        "openai_api_key": os.getenv("CRYSTALLIZE_OPENAI_API_KEY", ""),
        "llm_enable_thinking": _optional_bool_env("CRYSTALLIZE_LLM_ENABLE_THINKING"),
        "state_path": os.getenv(
            "CRYSTALLIZE_STATE_PATH",
            str(memory_state_dir() / "crystallize_state.json"),
        ),
        "audit_path": os.getenv(
            "CRYSTALLIZE_AUDIT_PATH",
            str(memory_state_dir() / "crystallize_audit.jsonl"),
        ),
        "search_strategy": _search_strategy_env(),
        "min_score": _optional_float_env("CRYSTALLIZE_MIN_SCORE"),
    }


def _projection_mode_env() -> str:
    value = os.getenv("SOLIDIFY_PROJECTION_MODE", "async").strip() or "async"
    if value not in {"async", "sync"}:
        raise ValueError("SOLIDIFY_PROJECTION_MODE must be async or sync")
    return value


def load_solidification_config() -> dict[str, Any]:
    """Load persistent solidification config from env vars.

    The solidification and crystallization layers are merged into a single switch: whether it is
    enabled is decided by CRYSTALLIZE_ENABLED (the caller writes the enabled field), and
    SOLIDIFY_ENABLED is no longer exposed separately.
    Also includes the ledger, vector projection, and phase-three mechanical maturity thresholds;
    all thresholds only participate in local counting and clock decisions, and do not trigger
    additional LLM calls.
    """
    return {
        "enabled": False,
        "db_path": os.getenv("SOLIDIFY_DB_PATH", str(memory_state_dir() / "solidification.db")),
        "crystal_collection": os.getenv("SOLIDIFY_CRYSTAL_COLLECTION", "crystals"),
        "document_enabled": os.getenv("SOLIDIFY_DOCUMENT_ENABLED", "true").lower() == "true",
        "doc_repo_path": os.getenv(
            "SOLIDIFY_DOC_REPO_PATH", str(memory_state_dir() / "crystal_docs")
        ),
        "doc_git_enabled": os.getenv("SOLIDIFY_DOC_GIT_ENABLED", "true").lower() == "true",
        "graph_enabled": os.getenv("SOLIDIFY_GRAPH_ENABLED", "true").lower() == "true",
        "projection_mode": _projection_mode_env(),
        "projection_batch_size": int(os.getenv("SOLIDIFY_PROJECTION_BATCH_SIZE", "100")),
        "embedding_batch_size": max(1, int(os.getenv("CRYSTALLIZE_EMBEDDING_BATCH_SIZE", "32"))),
        "search_workers": int(os.getenv("SOLIDIFY_SEARCH_WORKERS", "4")),
        "raw_search_timeout_seconds": float(
            os.getenv("SOLIDIFY_RAW_SEARCH_TIMEOUT_SECONDS", "10.0")
        ),
        "crystal_search_timeout_seconds": float(
            os.getenv("SOLIDIFY_CRYSTAL_SEARCH_TIMEOUT_SECONDS", "10.0")
        ),
        "crystal_candidate_limit": int(os.getenv("SOLIDIFY_CRYSTAL_CANDIDATE_LIMIT", "20")),
        "provenance_lookup_limit": int(os.getenv("SOLIDIFY_PROVENANCE_LOOKUP_LIMIT", "30")),
        "provenance_per_crystal": int(os.getenv("SOLIDIFY_PROVENANCE_PER_CRYSTAL", "5")),
        "maturity_enabled": os.getenv("SOLIDIFY_MATURITY_ENABLED", "true").lower() == "true",
        "maturity_sweep_seconds": float(os.getenv("SOLIDIFY_MATURITY_SWEEP_SECONDS", "60")),
        "active_min_confidence": float(os.getenv("SOLIDIFY_ACTIVE_MIN_CONFIDENCE", "0.65")),
        "canonical_min_runs": int(os.getenv("SOLIDIFY_CANONICAL_MIN_RUNS", "3")),
        "canonical_min_age_days": float(os.getenv("SOLIDIFY_CANONICAL_MIN_AGE_DAYS", "7")),
        "active_min_reinforcement": int(os.getenv("SOLIDIFY_ACTIVE_MIN_REINFORCEMENT", "2")),
        "active_direct_confidence": float(os.getenv("SOLIDIFY_ACTIVE_DIRECT_CONFIDENCE", "0.85")),
    }


def load_validity_config() -> dict[str, Any]:
    """Load validity verification config; effective must also be computed in tandem with the
    crystallization master switch."""
    return {
        "requested": os.getenv("VALIDITY_ENABLED", "false").lower() == "true",
        "effective": False,
        "scan_interval_seconds": float(os.getenv("VALIDITY_SCAN_INTERVAL_SECONDS", "30")),
        "full_audit_interval_seconds": float(
            os.getenv("VALIDITY_FULL_AUDIT_INTERVAL_SECONDS", "3600")
        ),
        "batch_size": int(os.getenv("VALIDITY_BATCH_SIZE", "50")),
        "max_cases_per_run": int(os.getenv("VALIDITY_MAX_CASES_PER_RUN", "20")),
        "case_lease_seconds": float(os.getenv("VALIDITY_CASE_LEASE_SECONDS", "120")),
        "max_attempts": int(os.getenv("VALIDITY_MAX_ATTEMPTS", "5")),
        "llm_enabled": os.getenv("VALIDITY_LLM_ENABLED", "true").lower() == "true",
        "llm_timeout_seconds": float(os.getenv("VALIDITY_LLM_TIMEOUT_SECONDS", "20")),
        "llm_min_risk": int(os.getenv("VALIDITY_LLM_MIN_RISK", "40")),
        "auto_apply_min_confidence": float(os.getenv("VALIDITY_AUTO_APPLY_MIN_CONFIDENCE", "0.85")),
        "max_evidence_per_crystal": int(os.getenv("VALIDITY_MAX_EVIDENCE_PER_CRYSTAL", "8")),
        "max_evidence_chars": int(os.getenv("VALIDITY_MAX_EVIDENCE_CHARS", "12000")),
        "policy_version": os.getenv("VALIDITY_POLICY_VERSION", "v1"),
    }
