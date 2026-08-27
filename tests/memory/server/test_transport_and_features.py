from __future__ import annotations

import importlib
import uuid
from typing import Any

import pytest
import requests

from clawcodex_ext.latent_memory.server.lib.crystallization.cluster import (
    cluster_similarity_graph,
)
from clawcodex_ext.latent_memory.server.lib.salience_gate import (
    HighValueSignalDetector,
    RuleBasedFilter,
    SalienceGate,
)
from clawcodex_ext.latent_memory.server.mcp_server import MemoryHttpClient, MemoryServerError
from clawcodex_ext.latent_memory.server.schemas import AddRequest, SearchRequest


def test_rule_gate_skips_noise_turn() -> None:
    messages = [{"role": "user", "content": "Thanks!"}]

    result = SalienceGate(ollama_gate=None).filter_messages(messages)

    assert result.skipped is True
    assert result.filtered_messages == []


def test_high_value_signal_keeps_user_preference() -> None:
    detector = HighValueSignalDetector()
    messages = [
        {
            "role": "user",
            "content": "I prefer PostgreSQL 16 and snake_case API fields.",
        }
    ]

    assert detector.has_high_value_signal(messages[0]["content"]) is True
    assert RuleBasedFilter().should_skip_turn(messages) is False


def test_crystallization_similarity_graph_groups_related_facts() -> None:
    pytest.importorskip("numpy")

    clusters, diagnostics = cluster_similarity_graph(
        [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]],
        [],
        min_cluster_size=2,
        cluster_create_similarity=0.90,
        cluster_absorb_similarity=0.90,
        cluster_min_avg_similarity=0.80,
        cluster_max_size=10,
    )

    assert any(cluster["raw_indices"] == [0, 1] for cluster in clusters)
    assert diagnostics["covered_raw"] == 2


def test_mcp_connection_error_contains_start_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_request(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "request", fail_request)

    with pytest.raises(MemoryServerError, match="clawcodex-dev memory enable"):
        MemoryHttpClient("http://127.0.0.1:8888").get("/health")


def test_rest_route_functions_keep_add_search_delete_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_module = importlib.import_module("clawcodex_ext.latent_memory.server.app")

    class StubService:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        @staticmethod
        def add_memories(request: AddRequest) -> dict[str, Any]:
            return {"results": [{"id": "memory-1", "event": "ADD"}], "request": request}

        @staticmethod
        def search_memories(request: SearchRequest) -> dict[str, Any]:
            return {"results": [{"id": "memory-1", "memory": request.query}]}

        def delete_memory(self, memory_id: str) -> None:
            self.deleted.append(memory_id)

        @staticmethod
        def health() -> dict[str, str]:
            return {"status": "ok", "llm": "fake", "embedder": "fake"}

    service = StubService()
    monkeypatch.setattr(app_module, "memory_service", service)
    add_request = AddRequest(
        messages=[{"role": "user", "content": "Prefer PostgreSQL"}],
        user_id="ccx:test",
    )
    search_request = SearchRequest(query="database", user_id="ccx:test", limit=3)
    memory_id = str(uuid.uuid4())

    added = app_module.add_memories(add_request)
    searched = app_module.search_memories(search_request)
    deleted = app_module.delete_memory(memory_id)

    assert added["results"][0]["event"] == "ADD"
    assert searched["results"][0]["memory"] == "database"
    assert deleted == {"message": "Memory deleted successfully"}
    assert service.deleted == [memory_id]
    assert app_module.health()["status"] == "ok"
