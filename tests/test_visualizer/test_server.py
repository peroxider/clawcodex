"""Tests for the Visualizer FastAPI server and API endpoints."""

from __future__ import annotations

import builtins
import json
import time
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

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
    (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # transcript.jsonl
    transcript = [
        json.dumps({"role": "user", "content": "hello", "timestamp": now - 60}),
        json.dumps(
            {
                "role": "assistant",
                "content": "reading file...",
                "timestamp": now - 58,
                "tool_calls": [
                    {
                        "id": "tc-001",
                        "type": "function",
                        "function": {"name": "Read", "arguments": {"file_path": "main.py"}},
                    }
                ],
            }
        ),
        json.dumps(
            {
                "role": "tool",
                "tool_call_id": "tc-001",
                "content": "file content",
                "timestamp": now - 57,
            }
        ),
    ]
    (session_dir / "transcript.jsonl").write_text("\n".join(transcript), encoding="utf-8")

    return sd


def _create_minimal_session(sessions_dir: Path, session_id: str) -> Path:
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    metadata = {
        "session_id": session_id,
        "title": session_id,
        "status": "completed",
        "start_time": now - 1,
        "end_time": now,
    }
    (session_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (session_dir / "transcript.jsonl").write_text(
        json.dumps({"role": "user", "content": "hello", "timestamp": now}),
        encoding="utf-8",
    )
    return session_dir


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

    def test_missing_sessions_dir_still_lists_default_workspace(self, tmp_path):
        from fastapi.testclient import TestClient
        from extensions.visualizer.server import create_app

        missing_dir = tmp_path / "missing-sessions"
        client = TestClient(create_app(sessions_dir=missing_dir, allow_import=False))

        resp = client.get("/api/viz/workspaces")
        assert resp.status_code == 200
        assert resp.json() == [
            {
                "id": "default",
                "name": "All sessions",
                "path": str(missing_dir),
                "session_count": 0,
                "last_updated": 0.0,
            }
        ]

        sessions_resp = client.get("/api/viz/workspaces/default/sessions")
        assert sessions_resp.status_code == 200
        assert sessions_resp.json() == []


class TestOrchestratorRoutes:
    def test_run_detail_preserves_issue_session_id(self, app, client, tmp_path):
        reports = tmp_path / "reports"
        run_dir = reports / "run_20260623_120000"
        run_dir.mkdir(parents=True)
        events = [
            {"type": "orchestrator_start", "timestamp": "2026-06-23T12:00:00Z", "workflow": "test"},
            {
                "type": "issue_status",
                "timestamp": "2026-06-23T12:00:01Z",
                "issue_id": "ISS-1",
                "status": "running",
            },
            {
                "type": "session_ref",
                "timestamp": "2026-06-23T12:00:02Z",
                "issue_id": "ISS-1",
                "session_id": "test-session-001",
                "session_path": "C:/tmp/test-session-001",
            },
        ]
        (run_dir / "state_journal.ndjson").write_text(
            "\n".join(json.dumps(item) for item in events), encoding="utf-8"
        )
        app.state.viz.reports_dir = reports

        resp = client.get("/api/viz/orchestrator/runs/run_20260623_120000")
        assert resp.status_code == 200
        issue = resp.json()["issues"]["ISS-1"]
        assert issue["session_id"] == "test-session-001"
        assert issue["session_path"].endswith("test-session-001")


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

    def test_gantt_endpoint_is_removed(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/gantt")
        assert resp.status_code == 404

    def test_get_session_report_links(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "export" in data

    def test_session_report_links_urlencode_session_id(self, sessions_dir, client):
        session_id = "session with #hash"
        session_dir = _create_minimal_session(sessions_dir, session_id)
        (session_dir / "report.md").write_text("# Encoded Report\n", encoding="utf-8")
        (session_dir / "events.ndjson").write_text('{"event":"ok"}\n', encoding="utf-8")
        (session_dir / "debug.ndjson").write_text('{"debug":"ok"}\n', encoding="utf-8")

        resp = client.get("/api/viz/sessions/session%20with%20%23hash/report")
        assert resp.status_code == 200
        links = resp.json()
        assert links["export"] == "/api/viz/sessions/session%20with%20%23hash/export"
        assert links["f38_report"] == "/api/viz/sessions/session%20with%20%23hash/report/f38"
        assert links["f45_events"] == "/api/viz/sessions/session%20with%20%23hash/report/f45"
        assert links["f54_debug"] == "/api/viz/sessions/session%20with%20%23hash/report/f54"
        assert client.get(links["f38_report"]).status_code == 200

    def test_session_report_links_are_resolvable(self, sessions_dir, client):
        session_dir = sessions_dir / "test-session-001"
        (session_dir / "report.md").write_text("# Report\n", encoding="utf-8")
        (session_dir / "events.ndjson").write_text('{"event":"ok"}\n', encoding="utf-8")
        (session_dir / "debug.ndjson").write_text('{"debug":"ok"}\n', encoding="utf-8")

        links_resp = client.get("/api/viz/sessions/test-session-001/report")
        assert links_resp.status_code == 200
        links = links_resp.json()

        report_resp = client.get(links["f38_report"])
        assert report_resp.status_code == 200
        assert "text/markdown" in report_resp.headers.get("content-type", "")
        assert report_resp.text.startswith("# Report")

        events_resp = client.get(links["f45_events"])
        assert events_resp.status_code == 200
        assert "application/x-ndjson" in events_resp.headers.get("content-type", "")
        assert '"event":"ok"' in events_resp.text

        debug_resp = client.get(links["f54_debug"])
        assert debug_resp.status_code == 200
        assert "application/x-ndjson" in debug_resp.headers.get("content-type", "")
        assert '"debug":"ok"' in debug_resp.text

    def test_missing_session_report_artifact_returns_404(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/report/f38")
        assert resp.status_code == 404

    def test_export_session_json(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=json")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/json"


class TestRemovedVisualizerSurfaces:
    @pytest.mark.parametrize(
        "path",
        [
            "/api/viz/compare?sessions=test-session-001",
            "/api/viz/compare/export",
            "/api/viz/multi-session?sessions=test-session-001",
            "/api/viz/turn/test-session-001__tool-1/llm-io",
            "/compare",
            "/multi",
        ],
    )
    def test_removed_surface_returns_404_or_405(self, client, path):
        assert client.get(path).status_code in (404, 405)


class TestShareLinks:
    def test_comparison_share_is_rejected(self, client):
        resp = client.post(
            "/api/viz/share",
            json={
                "session_id": "test-session-001",
                "view_type": "comparison",
            },
        )
        assert resp.status_code == 400

    def test_create_and_get_share_link(self, client):
        # Create
        resp = client.post(
            "/api/viz/share",
            json={
                "session_id": "test-session-001",
            },
        )
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
        resp = client.post(
            "/api/viz/share",
            json={
                "session_id": "test-session-001",
            },
        )
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
        resp = client.post(
            "/api/viz/import",
            json={
                "url": "https://example.com/data.json",
            },
        )
        assert resp.status_code == 404 or resp.status_code == 405

    def test_import_enabled(self, client):
        """With --allow-import, import endpoint exists."""
        resp = client.post(
            "/api/viz/import",
            json={
                "url": "https://example.com/data.json",
            },
        )
        # May fail for SSRF reasons, but endpoint should exist
        assert resp.status_code in (202, 400, 403)


class TestFrontend:
    def test_base_no_longer_references_removed_frontend_assets(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        removed = (
            "multi_session.css",
            "gantt.js",
            "bezier_waterfall.js",
            "multi_session_view.js",
            "utils.js",
            "echarts",
        )
        for needle in removed:
            assert needle not in resp.text

    def test_frontend_assets_do_not_contain_mojibake_or_placeholders(self, client):
        paths = (
            "/",
            "/session/test-session-001",
            "/static/js/app.js?v=20260623-clean-copy-1",
            "/static/js/session_view.js?v=20260623-clean-copy-1",
        )
        bad = (
            "???",
            "\u951f",
            "\u9225",
            "\u6d93?",
            "\u701b?",
            "\u93c3?",
            "\u5a32?",
            "\u93c8?",
            "\u93b5?",
            "\u9435?",
            "\u7eef?",
        )
        for path in paths:
            resp = client.get(path)
            assert resp.status_code == 200
            for token in bad:
                assert token not in resp.text

    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        # Should be HTML
        assert "text/html" in resp.headers.get("content-type", "")
        assert "app.js?v=20260623-clean-copy-1" in resp.text
        assert "style.css?v=20260623-clean-base-1" in resp.text
        assert (
            'id="layout-toggle-grid" class="layout-toggle-btn active" aria-pressed="true"'
            in resp.text
        )
        assert 'id="layout-toggle-list" class="layout-toggle-btn" aria-pressed="false"' in resp.text

    def test_index_app_renders_real_session_links(self, client):
        resp = client.get("/static/js/app.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert 'class="session-card" href="${href}"' in resp.text
        assert 'class="session-row" href="${href}"' in resp.text
        assert 'role="link"' not in resp.text
        assert "data-session-id" not in resp.text
        assert "safeClassPart(session.status)" in resp.text
        assert "status-${escapeHtml(session.status)}" not in resp.text
        assert "const VALID_STATUSES" in resp.text
        assert "readChoice('viz.statusFilter', VALID_STATUSES, 'all')" in resp.text
        assert "readChoice('viz.layoutMode', VALID_LAYOUTS, 'grid')" in resp.text
        assert "localStorage.getItem('viz.statusFilter') || 'all'" not in resp.text

    def test_index_app_ignores_stale_session_responses(self, client):
        resp = client.get("/static/js/app.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "sessionRequestSeq: 0" in resp.text
        assert "const requestSeq = ++state.sessionRequestSeq;" in resp.text
        assert "const sessions = await requestJson(sessionsUrl());" in resp.text
        assert "if (requestSeq !== state.sessionRequestSeq) return;" in resp.text
        success_guard = resp.text.index(
            "if (requestSeq !== state.sessionRequestSeq) return;",
            resp.text.index("const sessions = await requestJson"),
        )
        catch_start = resp.text.index("} catch (error) {", success_guard)
        catch_guard = resp.text.index(
            "if (requestSeq !== state.sessionRequestSeq) return;", catch_start
        )
        assign_start = resp.text.index("state.sessions = sessions;", success_guard)
        assert success_guard < assign_start < catch_start < catch_guard

    def test_index_app_sends_search_and_status_to_workspace_api(self, client):
        resp = client.get("/static/js/app.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "function sessionsUrl()" in resp.text
        assert "const params = new URLSearchParams();" in resp.text
        assert "if (query) params.set('q', query);" in resp.text
        assert "if (state.status !== 'all') params.set('status', state.status);" in resp.text
        assert "const sessions = await requestJson(sessionsUrl());" in resp.text
        assert "state.sessions = sessions;" in resp.text
        assert "state.query = event.target.value; loadSessions({ quiet: true });" in resp.text
        status_write = resp.text.index("writeChoice('viz.statusFilter', state.status);")
        status_reload = resp.text.index("loadSessions({ quiet: true });", status_write)
        assert status_write < status_reload

    def test_index_app_guards_storage_writes_and_refresh_order(self, client):
        resp = client.get("/static/js/app.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "const writeChoice = (key, value)" in resp.text
        assert "try { localStorage.setItem(key, value); } catch (_)" in resp.text
        assert "localStorage.setItem('viz.layoutMode', layout)" not in resp.text
        assert "localStorage.setItem('viz.statusFilter', state.status)" not in resp.text
        assert "await loadWorkspaces(); await loadSessions();" in resp.text
        assert (
            "loadWorkspaces().then(() => loadSessions({ quiet: true })).catch(() => setLiveState('error'))"
            in resp.text
        )
        initial_error = resp.text.index(
            "catch (error) {",
            resp.text.index("try { await loadWorkspaces(); await loadSessions(); }"),
        )
        interval_start = resp.text.index("state.timer = window.setInterval")
        assert "Cannot scan sessions" in resp.text[initial_error:interval_start]
        assert "setLiveState('error');" in resp.text[initial_error:interval_start]

    def test_index_app_cleans_up_background_polling(self, client):
        resp = client.get("/static/js/app.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "function stopPolling()" in resp.text
        assert "window.clearInterval(state.timer);" in resp.text
        assert "state.timer = null;" in resp.text
        assert "window.addEventListener('pagehide', stopPolling);" in resp.text
        assert "window.addEventListener('beforeunload', stopPolling);" in resp.text

    def test_session_view_refreshes_selected_drawer_after_live_reload(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        fetch_start = resp.text.index("async function fetchSession")
        render_start = resp.text.index("render();", fetch_start)
        refresh_start = resp.text.index("refreshSelectedDrawer();", render_start)
        helper_start = resp.text.index("function refreshSelectedDrawer()")
        assert fetch_start < render_start < refresh_start < helper_start
        assert "const selected = state.eventMap.get(state.selectedId);" in resp.text
        assert "if (selected) renderDrawer(selected, { focus: false });" in resp.text
        assert "function renderDrawer(event, { focus = true } = {})" in resp.text
        assert "if (focus) drawer.focus({ preventScroll: true });" in resp.text

    def test_session_view_closes_drawer_when_filter_hides_selected_event(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "const selected = state.eventMap.get(state.selectedId);" in resp.text
        assert (
            "if (selected && !state.active.has(categoryOf(selected))) closeDrawer();" in resp.text
        )
        toggle_start = resp.text.index("const selected = state.eventMap.get(state.selectedId);")
        render_start = resp.text.index("renderLegend();", toggle_start)
        assert toggle_start < render_start

    def test_session_view_sanitizes_badge_colors(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "safeCssColor(agent.badgeColor)" in resp.text
        assert "--badge-color:${escapeHtml(agent.badgeColor)}" not in resp.text

    def test_session_view_clamps_timeline_event_width(self, client):
        resp = client.get("/static/js/session_view.js?v=20260624-inline-1")
        assert resp.status_code == 200
        assert "const leftPercent = clampPercent" in resp.text
        assert (
            "const innerPixels = Math.max(1, range.innerTrackPixels || range.trackPixels || 1)"
            in resp.text
        )
        assert "const maxWidthPx = Math.max(1, TRACK_INSET + innerPixels - leftPx)" in resp.text
        assert "const hitWidthPx = Math.min(maxWidthPx, Math.max(widthPx, 8))" in resp.text
        assert "width:${geometry.hitWidthPx}px" in resp.text
        assert (
            "--event-actual-width:${Math.min(geometry.widthPx, geometry.hitWidthPx)}px" in resp.text
        )
        assert "width:${rawWidth}%" not in resp.text

    def test_session_view_keeps_dense_lane_events_inline(self, client):
        js_resp = client.get("/static/js/session_view.js?v=20260624-inline-1")
        assert js_resp.status_code == 200
        assert "function layoutLaneEvents(events, range)" in js_resp.text
        assert "visualLeftPx" in js_resp.text
        assert "cursor + EVENT_GAP_PX" in js_resp.text
        assert "EVENT_COMPACT_HIT_WIDTH" in js_resp.text
        assert "--event-top:${EVENT_TOP}px" in js_resp.text
        assert "is-stacked" not in js_resp.text

        css_resp = client.get("/static/css/session_view.css?v=20260624-inline-1")
        assert css_resp.status_code == 200
        assert "min-height: 46px" in css_resp.text
        assert "height: 38px" in css_resp.text
        assert "min-width: 0" in css_resp.text
        assert ".timeline-event.is-stacked" not in css_resp.text

    def test_session_view_shows_synthesized_subagents(self, client):
        resp = client.get("/static/js/session_view.js?v=20260624-inline-1")
        assert resp.status_code == 200
        assert "node.parent_id !== null && node.parent_id !== undefined" in resp.text
        assert "node.metadata?.transcript_path" not in resp.text
        assert "eventCenterPoint(subFirstEvent?.id" in resp.text
        assert "eventCenterPoint(subLastEvent?.id" in resp.text

    def test_session_view_highlights_agent_connectors_with_events(self, client):
        js_resp = client.get("/static/js/session_view.js?v=20260624-inline-1")
        assert js_resp.status_code == 200
        assert "connectorLinks: new Map()" in js_resp.text
        assert "node.metadata?.spawn_bar_id" in js_resp.text
        assert "appendConnectorId(eventId, connectorId)" in js_resp.text
        assert "setLinkedConnectorsHighlighted(button, true)" in js_resp.text
        assert "function bindConnectorHoverDelegation()" in js_resp.text
        assert "canvas.addEventListener('pointermove'" in js_resp.text
        assert "setHoveredConnectors(connectorIdsForTarget(pointer.target))" in js_resp.text
        assert 'data-connector-id="${escapeHtml(connectorId)}"' in js_resp.text
        assert "agent-connector-hit" in js_resp.text
        assert 'tabindex="0" role="button"' not in js_resp.text

        css_resp = client.get("/static/css/session_view.css?v=20260624-inline-1")
        assert css_resp.status_code == 200
        assert ".timeline-event.connector-highlighted" in css_resp.text
        assert ".agent-connectors { position: absolute; top: 0; z-index: 2;" in css_resp.text
        assert ".agent-connectors .agent-connector-hit" in css_resp.text
        assert "outline: none" in css_resp.text
        assert ".agent-connectors .connector-highlighted.agent-connector" in css_resp.text

    def test_session_view_drawer_uses_css_transition(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "drawer.classList.add('open')" in resp.text
        assert "drawer.classList.remove('open')" in resp.text
        assert "style.setProperty('transition'" not in resp.text
        assert "style.setProperty('left'" not in resp.text

    def test_session_view_disconnects_live_tail_on_page_exit(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "function disconnectLiveTail()" in resp.text
        assert "window.clearTimeout(state.reloadTimer);" in resp.text
        assert "window.vizWs.disconnect();" in resp.text
        assert "state.liveTailConnected = false;" in resp.text
        assert "window.addEventListener('pagehide', disconnectLiveTail);" in resp.text
        assert "window.addEventListener('beforeunload', disconnectLiveTail);" in resp.text

    def test_session_view_initialize_is_idempotent(self, client):
        resp = client.get("/static/js/session_view.js?v=20260623-clean-copy-1")
        assert resp.status_code == 200
        assert "controlsBound: false" in resp.text
        assert "liveTailConnected: false" in resp.text
        assert "if (state.controlsBound) return;" in resp.text
        assert "state.controlsBound = true;" in resp.text
        assert "if (window.vizWs && !state.liveTailConnected)" in resp.text
        assert "state.liveTailConnected = true;" in resp.text
        catch_start = resp.text.index("} catch (error) {")
        live_start = resp.text.index("if (window.vizWs && !state.liveTailConnected)")
        assert "return;" in resp.text[catch_start:live_start]

    def test_session_view_uses_clickable_hit_targets_for_short_events(self, client):
        css_resp = client.get("/static/css/session_view.css?v=20260623-hit-target-1")
        assert css_resp.status_code == 200
        assert "height: var(--event-height, 24px); min-width: 0; max-width: 100%;" in css_resp.text
        assert "background: transparent" in css_resp.text
        assert ".timeline-event::before" in css_resp.text
        assert "width: max(var(--event-actual-width), 2px)" in css_resp.text
        assert ".timeline-event.is-error::before" in css_resp.text
        assert "min-width: 3px" not in css_resp.text
        assert ".timeline-event.category-user, .timeline-event.category-system" not in css_resp.text
        assert ".lane-track::before" not in css_resp.text

    def test_session_view_zoom_reset_has_spacing(self, client):
        css_resp = client.get("/static/css/session_view.css?v=20260624-inline-1")
        assert css_resp.status_code == 200
        assert (
            ".zoom-controls button + button { border-left: 1px solid var(--timeline-border); }"
            in css_resp.text
        )
        assert "#zoom-reset { padding: 0 12px; }" in css_resp.text

    def test_session_view_labels_wide_timeline_events(self, client):
        js_resp = client.get("/static/js/session_view.js?v=20260624-inline-1")
        assert js_resp.status_code == 200
        assert "trackPixels" in js_resp.text
        assert "const showLabel = geometry.widthPx >= 44" in js_resp.text
        assert "timeline-event-label" in js_resp.text
        assert 'title="${escapeHtml(label)}"' in js_resp.text

        css_resp = client.get("/static/css/session_view.css?v=20260624-inline-1")
        assert css_resp.status_code == 200
        assert ".timeline-event.has-label" in css_resp.text
        assert ".timeline-event-label" in css_resp.text

    def test_subagent_toggle_arrow_is_centered_chevron(self, client):
        css_resp = client.get("/static/css/session_view.css?v=20260623-hit-target-1")
        assert css_resp.status_code == 200
        assert ".subagent-toggle-arrow {" in css_resp.text
        assert "position: relative; width: 20px; height: 20px" in css_resp.text
        assert 'content: ""; position: absolute; left: 50%; top: 50%' in css_resp.text
        assert "transform: translate(-50%, -50%) rotate(-45deg)" in css_resp.text
        assert "transform: translate(-50%, -50%) rotate(45deg)" in css_resp.text

    def test_orchestrator_dashboard_clamps_progress(self, client):
        resp = client.get("/viz/orchestrator")
        assert resp.status_code == 200
        assert "function progressPercent(value)" in resp.text
        assert "clampPercent(Math.round(Number(value) * 100))" in resp.text
        assert "progress=${progressPercent(ev.progress)}%" in resp.text
        assert "Math.round(ev.progress*100)" not in resp.text

    def test_orchestrator_issue_row_partial_is_hardened(self):
        templates_dir = Path("extensions/visualizer/templates")
        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("orchestrator_issue_row.html")
        html = template.render(
            issue={
                "issue_id": 'ISS" data-x="1',
                "session_id": "session with spaces/<x>",
                "status": 'bad status" onclick="x',
                "progress": 1.7,
                "pr_url": "javascript:evil()",
                "error": "<boom>",
            }
        )

        assert "loadIssueTimeline(this.dataset.issueId)" in html
        assert "javascript:" not in html
        assert 'onclick="x' not in html
        assert "width:100%" in html
        assert "badge-unknown" in html
        assert "session%20with%20spaces" in html
        assert "&lt;boom&gt;" in html

    def test_base_uses_neutral_live_tail_status(self, client):
        resp = client.get("/")
        assert "Live idle" in resp.text
        assert "Offline" not in resp.text
        assert "websocket.js?v=20260623-ws-encode-1" in resp.text

    def test_websocket_client_urlencodes_session_id(self, client):
        resp = client.get("/static/js/websocket.js?v=20260623-ws-encode-1")
        assert resp.status_code == 200
        assert "/api/viz/ws/sessions/${encodeURIComponent(sessionId)}" in resp.text
        assert "/api/viz/ws/sessions/${sessionId}" not in resp.text

    def test_session_page(self, client):
        resp = client.get("/session/test-session-001")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_session_page_uses_lane_assets(self, client):
        resp = client.get("/session/test-session-001")
        assert "session_view.css?v=20260624-inline-1" in resp.text
        assert "session_view.js?v=20260624-inline-1" in resp.text
        assert "echarts" not in resp.text.lower()

    def test_session_page_exposes_all_export_formats(self, client):
        resp = client.get("/session/test-session-001")
        assert 'href="/api/viz/sessions/test-session-001/export?format=json"' in resp.text
        assert 'href="/api/viz/sessions/test-session-001/export?format=svg"' in resp.text
        assert 'href="/api/viz/sessions/test-session-001/export?format=png"' in resp.text
        assert 'href="/api/viz/sessions/test-session-001/export?format=pdf"' in resp.text

    def test_session_page_urlencodes_export_links(self, sessions_dir, client):
        _create_minimal_session(sessions_dir, "session with #hash")
        resp = client.get("/session/session%20with%20%23hash")
        assert resp.status_code == 200
        assert 'href="/api/viz/sessions/session%20with%20%23hash/export?format=json"' in resp.text
        assert 'href="/api/viz/sessions/session%20with%20%23hash/export?format=pdf"' in resp.text
        assert 'href="/api/viz/sessions/session%20with%20%23hash/report"' in resp.text
        assert 'href="/api/viz/sessions/session with #hash/export' not in resp.text


class TestExportFormats:
    """Verify all export formats."""

    def test_export_content_disposition_handles_unicode_session_id(self, sessions_dir, client):
        session_id = "\u4e2d\u6587 session"
        _create_minimal_session(sessions_dir, session_id)
        resp = client.get(f"/api/viz/sessions/{quote(session_id, safe='')}/export?format=json")
        assert resp.status_code == 200
        header = resp.headers.get("content-disposition", "")
        assert 'filename="session.json"' in header
        assert "filename*=UTF-8''%E4%B8%AD%E6%96%87%20session.json" in header

    def test_attachment_disposition_is_header_safe(self):
        from extensions.visualizer.server import _attachment_disposition

        header = _attachment_disposition("\u4e2d\u6587 session #1.pdf")
        header.encode("latin-1")
        assert 'filename="session__1.pdf"' in header
        assert "filename*=UTF-8''%E4%B8%AD%E6%96%87%20session%20%231.pdf" in header

    def test_export_svg(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=svg")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers.get("content-type", "")
        assert 'filename="test-session-001.svg"' in resp.headers.get("content-disposition", "")

    def test_export_png(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=png")
        assert resp.status_code == 200
        assert "image/png" in resp.headers.get("content-type", "")
        assert 'filename="test-session-001.png"' in resp.headers.get("content-disposition", "")
        assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert not resp.content.lstrip().startswith(b"<svg")

    def test_export_png_without_pillow_still_returns_png(self, client, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("PIL"):
                raise ImportError("blocked by test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        resp = client.get("/api/viz/sessions/test-session-001/export?format=png")
        assert resp.status_code == 200
        assert "image/png" in resp.headers.get("content-type", "")
        assert 'filename="test-session-001.png"' in resp.headers.get("content-disposition", "")
        assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert not resp.content.lstrip().startswith(b"<svg")

    def test_export_pdf(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=pdf")
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers.get("content-type", "")
        assert 'filename="test-session-001.pdf"' in resp.headers.get("content-disposition", "")
        assert resp.content.startswith(b"%PDF-")
        assert b"%%EOF" in resp.content[-32:]
        assert not resp.content.lstrip().startswith(b"<svg")

    def test_export_pdf_without_reportlab_still_returns_pdf(self, client, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("reportlab"):
                raise ImportError("blocked by test")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        resp = client.get("/api/viz/sessions/test-session-001/export?format=pdf")
        assert resp.status_code == 200
        assert "application/pdf" in resp.headers.get("content-type", "")
        assert resp.content.startswith(b"%PDF-")
        assert b"%%EOF" in resp.content[-32:]
        assert not resp.content.lstrip().startswith(b"<svg")

    def test_export_invalid_format(self, client):
        resp = client.get("/api/viz/sessions/test-session-001/export?format=txt")
        assert resp.status_code == 422  # FastAPI validation error


class TestWorkspaceSearch:
    """Workspace session search/filter."""

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

    def test_search_sessions_by_provider_workspace_status_and_tag(self, sessions_dir, client):
        session_dir = _create_minimal_session(sessions_dir, "search-rich")
        metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
        metadata.update(
            {
                "provider": "needle-provider",
                "workspace": "needle-workspace",
                "status": "failed",
                "tags": ["needle-tag"],
            }
        )
        (session_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        for query in ("needle-provider", "needle-workspace", "failed", "needle-tag"):
            resp = client.get(f"/api/viz/workspaces/default/sessions?q={query}")
            assert resp.status_code == 200
            ids = {item["session_id"] for item in resp.json()}
            assert "search-rich" in ids

    def test_filter_sessions_by_status(self, sessions_dir, client):
        session_dir = _create_minimal_session(sessions_dir, "failed-only")
        metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
        metadata["status"] = "failed"
        (session_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

        failed_resp = client.get("/api/viz/workspaces/default/sessions?status=failed")
        assert failed_resp.status_code == 200
        failed_ids = {item["session_id"] for item in failed_resp.json()}
        assert "failed-only" in failed_ids
        assert "test-session-001" not in failed_ids

        all_resp = client.get("/api/viz/workspaces/default/sessions?status=all")
        assert all_resp.status_code == 200
        all_ids = {item["session_id"] for item in all_resp.json()}
        assert {"failed-only", "test-session-001"}.issubset(all_ids)

    def test_search_sessions_no_match(self, client):
        resp = client.get("/api/viz/workspaces/default/sessions?q=zzzzznonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestShareLinkPersistence:
    """Share link disk persistence."""

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
