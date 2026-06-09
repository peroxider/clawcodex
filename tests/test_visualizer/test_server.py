"""Tests for the Visualizer FastAPI server and API endpoints (F-92)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# We test with a temporary sessions dir to avoid touching real data


@pytest.fixture
def sessions_dir(tmp_path):
    """Create a temporary sessions directory with sample data."""
    sd = tmp_path / "sessions"
    sd.mkdir()

    # Create a demo session
    session_id = "test-session-001"
    session_dir = sd / session_id
    session_dir.mkdir()

    now = time.time()

    # metadata.json
    metadata = {
        "session_id": session_id,
        "title": "Test Session",
        "workspace": str(tmp_path),
        "model": "test-model",
        "provider": "test",
        "status": "completed",
        "start_time": now - 60,
        "end_time": now,
        "duration_ms": 60000,
        "turn_count": 3,
        "tool_count": 2,
    }
    (session_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # transcript.jsonl
    transcript = [
        json.dumps({"role": "user", "content": "hello", "timestamp": now - 60}),
        json.dumps({
            "role": "assistant",
            "content": "reading file...",
            "timestamp": now - 58,
            "tool_calls": [{
                "id": "tc-001",
                "type": "function",
                "function": {"name": "Read", "arguments": {"file_path": "main.py"}},
            }],
        }),
        json.dumps({
            "role": "tool",
            "tool_call_id": "tc-001",
            "content": "file content",
            "timestamp": now - 57,
        }),
    ]
    (session_dir / "transcript.jsonl").write_text(
        "\n".join(transcript), encoding="utf-8"
    )

    return sd


@pytest.fixture
def app(sessions_dir):
    """Create a test FastAPI app."""
    from extensions.visualizer.server import create_app
    return create_app(sessions_dir=sessions_dir, allow_import=True)


@pytest.fixture
def client(app):
    """Create a test client."""
    from fastapi.testclient import TestClient
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/viz/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["allow_import"] is True


class TestWorkspaces:
    def test_list_workspaces(self, client):
        resp = client.get("/api/viz/workspaces")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestSessionAPI:
    def test_get_session(self, client):
        resp = client.get("/api/viz/sessions/test-session-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-session-001"
        assert data["title"] == "Test Session"
        assert "timeline" in data

    def test_get_session_not_found(self, client):
        resp = client.get("/api/viz/sessions/nonexistent")
        assert resp.status_code == 404

    def test_get_session_stats(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_ops" in data

    def test_get_session_anomalies(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_session_tree(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/tree")
        assert resp.status_code == 200

    def test_get_session_gantt(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/gantt")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "series" in data
        assert "timeRange" in data

    def test_get_session_gantt_absolute(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/gantt?time_mode=absolute")
        assert resp.status_code == 200

    def test_get_session_report_links(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "export" in data

    def test_export_session_json(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=json")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"


class TestComparison:
    def test_compare_sessions(self, client):
        resp = client.get("/api/viz/compare?sessions=test-session-001")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data


class TestShareLinks:
    def test_create_and_get_share_link(self, client):
        # Create
        resp = client.post("/api/viz/share", json={
            "session_id": "test-session-001",
            "view_type": "session",
        })
        assert resp.status_code == 200
        share = resp.json()
        link_id = share["id"]

        # Get
        resp = client.get(f"/api/viz/share/{link_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "share" in data
        assert "data" in data

    def test_delete_share_link(self, client):
        # Create
        resp = client.post("/api/viz/share", json={
            "session_id": "test-session-001",
        })
        share = resp.json()
        link_id = share["id"]

        # Delete
        resp = client.delete(f"/api/viz/share/{link_id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = client.get(f"/api/viz/share/{link_id}")
        assert resp.status_code == 404

    def test_get_nonexistent_share(self, client):
        resp = client.get("/api/viz/share/nonexistent")
        assert resp.status_code == 404


class TestImportAPI:
    def test_import_disabled_by_default(self, tmp_path):
        """Without --allow-import, the import router is not mounted."""
        from extensions.visualizer.server import create_app
        app = create_app(sessions_dir=tmp_path, allow_import=False)
        from fastapi.testclient import TestClient
        client = TestClient(app)
        # Import endpoint should not exist
        resp = client.post("/api/viz/import", json={
            "url": "https://example.com/data.json",
        })
        assert resp.status_code == 404 or resp.status_code == 405

    def test_import_enabled(self, client):
        """With --allow-import, import endpoint exists."""
        resp = client.post("/api/viz/import", json={
            "url": "https://example.com/data.json",
        })
        # May fail for SSRF reasons, but endpoint should exist
        assert resp.status_code in (202, 400, 403)


class TestFrontend:
    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # Should be HTML
        assert "text/html" in resp.headers.get("content-type", "")

    def test_session_page(self, client):
        resp = client.get("/session/test-session-001")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_comparison_page(self, client):
        """The /compare frontend page renders successfully."""
        resp = client.get("/compare?sessions=test-session-001")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestExportFormats:
    """Verify all export formats (F-92-C)."""

    def test_export_svg(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=svg")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers.get("content-type", "")
        assert resp.headers.get("content-disposition", "").endswith(".svg\"")

    def test_export_png(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=png")
        assert resp.status_code == 200
        assert "image/png" in resp.headers.get("content-type", "")
        assert resp.headers.get("content-disposition", "").endswith(".png\"")

    def test_export_pdf(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=pdf")
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers.get("content-type", "")
        assert resp.headers.get("content-disposition", "").endswith(".pdf\"")

    def test_export_invalid_format(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=txt")
        assert resp.status_code == 422  # FastAPI validation error


class TestWorkspaceSearch:
    """Workspace session search/filter (F-93-B)."""

    def test_list_workspace_sessions(self, client):
        resp = client.get("/api/viz/workspaces/default/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Summary objects should not contain timeline data
        if len(data) > 0:
            assert "timeline" not in data[0]
            assert "session_id" in data[0]

    def test_search_sessions_by_query(self, client):
        resp = client.get("/api/viz/workspaces/default/sessions?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_search_sessions_no_match(self, client):
        resp = client.get("/api/viz/workspaces/default/sessions?q=zzzzznonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestShareLinkPersistence:
    """Share link disk persistence (F-95-B)."""

    def test_persistence_preserves_links_across_app_restart(self, sessions_dir, tmp_path):
        """Create a share link, then recreate the app — the link should survive."""
        from extensions.visualizer.server import create_app

        # First app instance
        app1 = create_app(sessions_dir=sessions_dir, allow_import=False)
        from fastapi.testclient import TestClient
        client1 = TestClient(app1)

        resp = client1.post("/api/viz/share", json={"session_id": "test-session-001"})
        assert resp.status_code == 200
        link_id = resp.json()["id"]

        # Force persistence
        app1.state.viz._save_share_links()
        shares_path = app1.state.viz._shares_path
        assert shares_path.exists()

        # Second app instance — should load from disk
        app2 = create_app(sessions_dir=sessions_dir, allow_import=False)
        client2 = TestClient(app2)

        resp2 = client2.get(f"/api/viz/share/{link_id}")
        assert resp2.status_code == 200, "Share link should survive across app restarts"
        data = resp2.json()
        assert data["share"]["id"] == link_id
