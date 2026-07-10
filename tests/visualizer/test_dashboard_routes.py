"""Tests for F-120 Visualizer dashboard routes and WebSocket."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from extensions.agent_dashboard import (
    DashboardEntry,
    DashboardSourceRegistry,
    DashboardStore,
    reset_default_store,
)
from extensions.visualizer.server import create_app


class _StaticSource:
    def __init__(self, name: str, entries: list[DashboardEntry]):
        self._name = name
        self._entries = entries

    @property
    def source_name(self) -> str:
        return self._name

    @property
    def cache_ttl_ms(self) -> int:
        return 5_000

    def pull(self, **filters: Any) -> list[DashboardEntry]:
        return list(self._entries)


@pytest.fixture
def store(tmp_path: Path) -> DashboardStore:
    reg = DashboardSourceRegistry()
    reg.register(
        _StaticSource(
            "goal",
            [
                DashboardEntry(
                    id="goal:t1",
                    source="goal",
                    title="ship X",
                    status="in_progress",
                    progress_pct=0.4,
                    detail="50 / 100 tokens",
                ),
                DashboardEntry(
                    id="goal:t2",
                    source="goal",
                    title="ship Y",
                    status="completed",
                ),
            ],
        )
    )
    reg.register(
        _StaticSource(
            "task",
            [
                DashboardEntry(
                    id="task:1",
                    source="task",
                    title="write tests",
                    status="pending",
                ),
            ],
        )
    )
    return DashboardStore(registry=reg, archive_dir=None)


@pytest.fixture
def client(store: DashboardStore, tmp_path: Path) -> TestClient:
    app = create_app(
        sessions_dir=tmp_path / "sessions",
        transcripts_dir=tmp_path / "transcripts",
        allow_import=False,
    )
    app.state.viz.dashboard_store = store
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_default_store() -> None:
    reset_default_store()


def test_dashboard_snapshot_returns_entries(client: TestClient) -> None:
    resp = client.get("/api/dashboard/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    ids = {item["id"] for item in data}
    assert "goal:t1" in ids
    assert "task:1" in ids


def test_dashboard_snapshot_filters_by_source(client: TestClient) -> None:
    resp = client.get("/api/dashboard/snapshot?source=goal")
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["source"] == "goal" for item in data)
    assert {item["id"] for item in data} == {"goal:t1", "goal:t2"}


def test_dashboard_snapshot_filters_by_status(client: TestClient) -> None:
    resp = client.get("/api/dashboard/snapshot?status=completed")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "goal:t2"


def test_dashboard_page_renders(client: TestClient) -> None:
    resp = client.get("/viz/dashboard")
    assert resp.status_code == 200
    text = resp.text
    assert "Agent Dashboard" in text
    assert "api/dashboard/snapshot" in text or "ws/dashboard/live" in text


def test_dashboard_websocket_sends_initial_snapshot(
    client: TestClient,
) -> None:
    with client.websocket_connect("/api/viz/ws/dashboard/live") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "dashboard_snapshot"
    assert isinstance(msg["entries"], list)
    assert len(msg["entries"]) == 3


def test_dashboard_websocket_receives_push_on_change(
    client: TestClient,
    store: DashboardStore,
) -> None:
    extra = _StaticSource(
        "extra",
        [
            DashboardEntry(
                id="extra:1",
                source="extra",
                title="new item",
                status="pending",
            ),
        ],
    )
    with client.websocket_connect("/api/viz/ws/dashboard/live") as ws:
        first = ws.receive_json()
        assert first["type"] == "dashboard_snapshot"
        store.register_source(extra)
        store.snapshot()
        pushed = ws.receive_json()
    assert pushed["type"] == "dashboard_snapshot"
    ids = {item["id"] for item in pushed["entries"]}
    assert "extra:1" in ids


def test_dashboard_websocket_heartbeat(client: TestClient) -> None:
    """Server should respond to a ping with pong."""
    with client.websocket_connect("/api/viz/ws/dashboard/live") as ws:
        ws.receive_json()  # initial snapshot
        ws.send_text("ping")
        response = ws.receive_text()
    assert response == "pong"
