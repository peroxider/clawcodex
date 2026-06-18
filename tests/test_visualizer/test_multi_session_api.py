"""Tests for the /api/viz/multi-session endpoint and /multi page (F-95)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def two_sessions_dir(tmp_path: Path) -> Path:
    """Create a sessions dir with two demo sessions for multi-session API tests."""
    sd = tmp_path / "sessions"
    sd.mkdir()
    now = time.time()

    for sid, model, status in [
        ("ms-session-a", "claude-opus-4-7", "completed"),
        ("ms-session-b", "claude-opus-4-7", "completed"),
    ]:
        d = sd / sid
        d.mkdir()
        meta = {
            "session_id": sid,
            "title": f"Test {sid}",
            "model": model,
            "status": status,
            "start_time": now - 60,
            "end_time": now,
            "duration_ms": 60000,
            "turn_count": 3,
            "tool_count": 3,
            "detected_mode": "single",
        }
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        # Minimal transcript
        (d / "transcript.jsonl").write_text(
            json.dumps({"role": "assistant", "content": "hi", "_timestamp": now - 60}) + "\n",
            encoding="utf-8",
        )
    return sd


@pytest.fixture
def app(two_sessions_dir: Path):
    from extensions.visualizer.server import create_app

    return create_app(sessions_dir=two_sessions_dir, allow_import=False)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


class TestMultiSessionAPI:
    def test_single_session_ok(self, client):
        resp = client.get("/api/viz/multi-session?sessions=ms-session-a")
        assert resp.status_code == 200
        data = resp.json()
        # Schema contract
        for k in ("timeRange", "legend", "sessions", "agents", "edges"):
            assert k in data, f"missing {k}"
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "ms-session-a"
        # Legend has 8 categories (F-95 follow-up — full OperationCategory set)
        assert len(data["legend"]) == 8

    def test_two_sessions_aligned_on_shared_axis(self, client):
        resp = client.get("/api/viz/multi-session?sessions=ms-session-a,ms-session-b")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 2
        # Both sessions have y rows starting at 0
        ys = [s["y"] for s in data["sessions"]]
        assert ys == [0, 1]

    def test_too_many_sessions_rejected(self, client):
        resp = client.get("/api/viz/multi-session?sessions=a,b,c,d,e,f")
        assert resp.status_code == 400

    def test_empty_sessions_rejected(self, client):
        resp = client.get("/api/viz/multi-session?sessions=")
        assert resp.status_code == 400

    def test_nonexistent_session_returns_404(self, client):
        resp = client.get("/api/viz/multi-session?sessions=does-not-exist")
        assert resp.status_code == 404

    def test_partial_match_succeeds_for_found(self, client):
        """If some sessions are missing, we still return the found ones."""
        resp = client.get("/api/viz/multi-session?sessions=ms-session-a,nope-1,nope-2")
        assert resp.status_code == 200
        data = resp.json()
        # Only ms-session-a is in the payload
        assert len(data["sessions"]) == 1

    def test_legend_includes_all_eight_categories(self, client):
        resp = client.get("/api/viz/multi-session?sessions=ms-session-a")
        data = resp.json()
        cats = [l["category"] for l in data["legend"]]
        # F-95 follow-up: full 8-category breakdown, with LLM_TEXT / TURN /
        # BACKGROUND no longer rolled into OTHER. Order is fixed by
        # _LEGEND_CATEGORIES in multi_session_view_builder.py.
        assert cats == [
            "read",
            "execute",
            "write",
            "orchestrate",
            "llm_text",
            "turn",
            "background",
            "other",
        ]

    def test_time_range_is_non_negative(self, client):
        resp = client.get("/api/viz/multi-session?sessions=ms-session-a,ms-session-b")
        data = resp.json()
        assert data["timeRange"]["min"] == 0.0
        assert data["timeRange"]["max"] >= data["timeRange"]["min"]


class TestMultiSessionPage:
    def test_multi_page_renders(self, client):
        resp = client.get("/multi")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_multi_page_with_query_param(self, client):
        resp = client.get("/multi?session_ids=ms-session-a,ms-session-b")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
