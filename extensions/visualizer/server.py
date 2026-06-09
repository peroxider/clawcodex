"""Independent FastAPI application for the Visualizer (F-92-A, Route B).

Start via ``clawcodex viz`` CLI or ``python -m extensions.visualizer.server``.
Default port 8765; expose ``mount_viz(app)`` for future F-82 merge.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .models.viz_models import (
    ComparisonResult,
    ExportFormat,
    ImportStatus,
    SessionVizData,
    ShareLink,
    WorkspaceInfo,
)
from .builders.comparison_builder import ComparisonBuilder
from .builders.export_builder import ExportBuilder
from .builders.gantt_data_builder import GanttDataBuilder
from .builders.stats_builder import StatsBuilder
from .builders.anomaly_builder import AnomalyBuilder
from .builders.timeline_builder import TimelineBuilder
from .import_router import create_import_router
from .ws import create_ws_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State: shared across requests
# ---------------------------------------------------------------------------

class _AppState:
    """Mutable app state that lives on ``app.state.viz``."""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        workspaces_file: Path | None = None,
        allow_import: bool = False,
    ) -> None:
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")
        self.workspaces_file = workspaces_file or (Path.home() / ".clawcodex" / "workspaces.json")
        self.allow_import = allow_import
        self.timeline_builder = TimelineBuilder(sessions_dir=self.sessions_dir)
        self.gantt_builder = GanttDataBuilder()
        self.comparison_builder = ComparisonBuilder()
        self.export_builder = ExportBuilder()
        self.stats_builder = StatsBuilder()
        self.anomaly_builder = AnomalyBuilder()
        self.share_links: dict[str, ShareLink] = {}
        self.import_tasks: dict[str, ImportStatus] = {}
        self._shares_path = Path.home() / ".clawcodex" / "viz_shares.json"
        # Load persisted share links
        self._load_share_links()

    # ------------------------------------------------------------------
    # Share link persistence (F-95-B)
    # ------------------------------------------------------------------

    def _load_share_links(self) -> None:
        """Load share links from disk, filtering expired entries."""
        import json
        import time
        if not self._shares_path.exists():
            return
        try:
            data = json.loads(self._shares_path.read_text(encoding="utf-8"))
            now = time.time()
            for item in data:
                if item.get("expires_at", 0) > now:
                    try:
                        share = ShareLink(**item)
                        self.share_links[share.id] = share
                    except Exception:
                        continue
        except Exception:
            logger.debug("Failed to load share links", exc_info=True)

    def _save_share_links(self) -> None:
        """Persist active share links to disk."""
        import json
        import time
        try:
            now = time.time()
            # Only persist non-expired
            active = [s for s in self.share_links.values() if s.expires_at > now]
            self._shares_path.parent.mkdir(parents=True, exist_ok=True)
            self._shares_path.write_text(
                json.dumps([s.model_dump(mode="json") for s in active], indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("Failed to save share links", exc_info=True)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks."""
    logger.info(
        "Visualizer server starting — sessions_dir=%s, allow_import=%s",
        app.state.viz.sessions_dir,
        app.state.viz.allow_import,
    )
    yield
    # Save share links on shutdown
    app.state.viz._save_share_links()
    logger.info("Visualizer server shutting down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    sessions_dir: Path | None = None,
    workspaces_file: Path | None = None,
    allow_import: bool = False,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> FastAPI:
    """Create the standalone Visualizer FastAPI app (Route B)."""
    app = FastAPI(
        title="ClawCodex Visualizer",
        version="0.1.0",
        lifespan=lifespan,
    )

    # State
    app.state.viz = _AppState(
        sessions_dir=sessions_dir,
        workspaces_file=workspaces_file,
        allow_import=allow_import,
    )

    # CORS — allow all for local dev
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(create_ws_router(), prefix="/api/viz")
    if allow_import:
        app.include_router(create_import_router(), prefix="/api/viz")

    # Templates & static files
    _this_dir = Path(__file__).resolve().parent
    templates_dir = _this_dir / "templates"
    static_dir = _this_dir / "static"

    if templates_dir.is_dir():
        app.state.templates = Jinja2Templates(directory=str(templates_dir))
    else:
        app.state.templates = None

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- API routes -------------------------------------------------------

    @app.get("/api/viz/health", tags=["health"])
    async def health():
        """Health check + allow_import status."""
        return {
            "status": "ok",
            "allow_import": app.state.viz.allow_import,
            "sessions_dir": str(app.state.viz.sessions_dir),
        }

    @app.get("/api/viz/workspaces", response_model=list[WorkspaceInfo], tags=["workspace"])
    async def list_workspaces():
        """List registered workspaces."""
        return _list_workspaces(app)

    @app.get("/api/viz/workspaces/{workspace_id}/sessions", tags=["workspace"])
    async def list_workspace_sessions(workspace_id: str, q: str | None = None):
        """List sessions in a workspace, optional text search."""
        sessions = _list_sessions_in_workspace(app, workspace_id)
        if q:
            q_lower = q.lower()
            sessions = [
                s for s in sessions
                if q_lower in s.session_id.lower()
                or q_lower in (s.title or "").lower()
                or q_lower in (s.agent_name or "").lower()
            ]
        # Return light summary (no timeline) for list view
        return [_session_summary(s) for s in sessions]

    @app.get("/api/viz/sessions/{session_id}", response_model=SessionVizData, tags=["session"])
    async def get_session(session_id: str):
        """Get complete viz data for a single session."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return viz

    @app.get("/api/viz/sessions/{session_id}/stats", tags=["session"])
    async def get_session_stats(session_id: str):
        """Get statistics for a session."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return viz.stats

    @app.get("/api/viz/sessions/{session_id}/anomalies", tags=["session"])
    async def get_session_anomalies(session_id: str):
        """Get anomalies for a session."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return viz.anomalies

    @app.get("/api/viz/sessions/{session_id}/tree", tags=["session"])
    async def get_session_tree(session_id: str):
        """Get multi-agent tree for a session."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return viz.agent_tree

    @app.get("/api/viz/sessions/{session_id}/gantt", tags=["session"])
    async def get_session_gantt(
        session_id: str,
        time_mode: str = Query("relative", pattern="^(relative|absolute|window)$"),
    ):
        """Get ECharts gantt data for a session."""
        from .models.viz_models import TimeMode
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        builder = GanttDataBuilder(time_mode=TimeMode(time_mode))
        return builder.build(viz)

    @app.get("/api/viz/sessions/{session_id}/report", tags=["session"])
    async def get_session_report(session_id: str):
        """Get F-38/F-45/F-54 report links for a session."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        links: dict[str, str | None] = {}
        if viz.report_path:
            links["f38_report"] = f"/api/viz/sessions/{session_id}/report/f38"
        if viz.tool_events_path:
            links["f45_events"] = f"/api/viz/sessions/{session_id}/report/f45"
        if viz.debug_log_path:
            links["f54_debug"] = f"/api/viz/sessions/{session_id}/report/f54"
        links["export"] = f"/api/viz/sessions/{session_id}/export"
        return links

    @app.get("/api/viz/sessions/{session_id}/export", tags=["export"])
    async def export_session(session_id: str, format: str = Query("json", pattern="^(png|svg|json|pdf)$")):
        """Export session data in the specified format."""
        viz = app.state.viz.timeline_builder.build(session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        fmt = ExportFormat(format)
        content, mime, filename = app.state.viz.export_builder.export_session(viz, fmt)
        from fastapi.responses import Response
        return Response(content=content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/viz/compare", tags=["comparison"])
    async def compare_sessions(sessions: str = Query(..., description="Comma-separated session IDs")):
        """Compare data across multiple sessions."""
        session_ids = [s.strip() for s in sessions.split(",") if s.strip()]
        if not session_ids:
            raise HTTPException(status_code=400, detail="At least one session ID required")
        viz_list: list[SessionVizData] = []
        for sid in session_ids:
            viz = app.state.viz.timeline_builder.build(sid)
            if viz:
                viz_list.append(viz)
        if not viz_list:
            raise HTTPException(status_code=404, detail="No sessions found")
        result = app.state.viz.comparison_builder.build(viz_list)
        return result

    @app.post("/api/viz/compare/export", tags=["comparison"])
    async def export_comparison(
        sessions: str = Query(..., description="Comma-separated session IDs"),
        format: str = Query("pdf", pattern="^(json|pdf)$"),
    ):
        """Export comparison report."""
        session_ids = [s.strip() for s in sessions.split(",") if s.strip()]
        viz_list: list[SessionVizData] = []
        for sid in session_ids:
            viz = app.state.viz.timeline_builder.build(sid)
            if viz:
                viz_list.append(viz)
        if not viz_list:
            raise HTTPException(status_code=404, detail="No sessions found")
        result = app.state.viz.comparison_builder.build(viz_list)
        fmt = ExportFormat(format)
        content, mime, filename = app.state.viz.export_builder.export_comparison(result, fmt)
        from fastapi.responses import Response
        return Response(content=content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    # --- Share links (F-92-D) ---------------------------------------------

    @app.post("/api/viz/share", tags=["share"])
    async def create_share_link(request: Request):
        """Create a share link for a session or comparison."""
        import time
        import uuid

        body = await request.json()
        session_id = body.get("session_id", "")
        view_type = body.get("view_type", "session")
        fmt = ExportFormat(body.get("format", "json"))

        link_id = uuid.uuid4().hex[:12]
        now = time.time()
        share = ShareLink(
            id=link_id,
            session_id=session_id,
            created_at=now,
            expires_at=now + 7 * 86400,  # 7-day TTL
            format=fmt,
            view_type=view_type,
            payload=body.get("payload", {}),
        )
        app.state.viz.share_links[link_id] = share
        app.state.viz._save_share_links()
        return share

    @app.get("/api/viz/share/{link_id}", tags=["share"])
    async def get_share_link(link_id: str):
        """Retrieve a share link."""
        share = app.state.viz.share_links.get(link_id)
        if share is None:
            raise HTTPException(status_code=404, detail="Share link not found")
        import time
        if time.time() > share.expires_at:
            del app.state.viz.share_links[link_id]
            app.state.viz._save_share_links()
            raise HTTPException(status_code=410, detail="Share link expired")
        # Return the full session data for this share
        viz = app.state.viz.timeline_builder.build(share.session_id)
        if viz is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"share": share, "data": viz}

    @app.delete("/api/viz/share/{link_id}", tags=["share"])
    async def delete_share_link(link_id: str):
        """Delete a share link."""
        if link_id not in app.state.viz.share_links:
            raise HTTPException(status_code=404, detail="Share link not found")
        del app.state.viz.share_links[link_id]
        app.state.viz._save_share_links()
        return {"status": "deleted"}

    # --- Frontend (Jinja2 SSR) -------------------------------------------

    @app.get("/", response_class=HTMLResponse, tags=["frontend"])
    async def index(request: Request):
        """Main gantt chart page."""
        if app.state.templates is None:
            return HTMLResponse("<h1>ClawCodex Visualizer</h1><p>Templates not found.</p>")
        workspaces = _list_workspaces(app)
        # Serialize workspaces to plain dicts for template context
        ws_data = [w.model_dump(mode="json") if hasattr(w, "model_dump") else w for w in workspaces]
        return app.state.templates.TemplateResponse(
            request, "index.html",
            {"workspaces": ws_data, "page_title": "ClawCodex Visualizer"},
        )

    @app.get("/session/{session_id}", response_class=HTMLResponse, tags=["frontend"])
    async def session_detail(request: Request, session_id: str):
        """Single session detail page."""
        if app.state.templates is None:
            return HTMLResponse(f"<h1>Session {session_id}</h1><p>Templates not found.</p>")
        return app.state.templates.TemplateResponse(
            request, "session_row.html",
            {"session_id": session_id, "page_title": f"Session {session_id}"},
        )

    @app.get("/compare", response_class=HTMLResponse, tags=["frontend"])
    async def compare_page(request: Request):
        """Cross-session comparison page."""
        if app.state.templates is None:
            return HTMLResponse("<h1>Compare Sessions</h1><p>Templates not found.</p>")
        return app.state.templates.TemplateResponse(
            request, "comparison.html",
            {"page_title": "Compare Sessions"},
        )

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_workspaces(app: FastAPI) -> list[WorkspaceInfo]:
    """Enumerate workspaces from workspaces.json or sessions_dir scan."""
    import json
    import time

    state: _AppState = app.state.viz

    # Try workspaces.json first
    if state.workspaces_file.exists():
        try:
            data = json.loads(state.workspaces_file.read_text(encoding="utf-8"))
            return [
                WorkspaceInfo(
                    id=w.get("id", ""),
                    name=w.get("name", w.get("id", "")),
                    path=w.get("path", ""),
                    session_count=w.get("session_count", 0),
                    last_updated=w.get("last_updated", 0.0),
                )
                for w in data
            ]
        except Exception:
            logger.debug("Failed to parse workspaces.json", exc_info=True)

    # Fallback: scan sessions_dir for distinct workspace prefixes
    workspaces: dict[str, WorkspaceInfo] = {}
    if state.sessions_dir.is_dir():
        for session_dir in state.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            # Use parent path as workspace identifier
            ws_name = session_dir.name.split("-")[0] if "-" in session_dir.name else "default"
            if ws_name not in workspaces:
                workspaces[ws_name] = WorkspaceInfo(
                    id=ws_name,
                    name=ws_name,
                    path=str(state.sessions_dir),
                    session_count=0,
                    last_updated=0.0,
                )
            workspaces[ws_name].session_count += 1
            try:
                mtime = session_dir.stat().st_mtime
                if mtime > workspaces[ws_name].last_updated:
                    workspaces[ws_name].last_updated = mtime
            except OSError:
                pass

    return list(workspaces.values())


def _list_sessions_in_workspace(app: FastAPI, workspace_id: str) -> list[SessionVizData]:
    """List all sessions for a given workspace."""
    state: _AppState = app.state.viz
    sessions: list[SessionVizData] = []

    if not state.sessions_dir.is_dir():
        return sessions

    for session_dir in sorted(state.sessions_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        sid = session_dir.name
        viz = state.timeline_builder.session_parser.parse(sid)
        if viz is not None:
            # Filter by workspace if possible
            if viz.workspace and workspace_id != "default":
                # Match workspace ID against workspace path/name
                if workspace_id.lower() not in viz.workspace.lower():
                    continue
            sessions.append(viz)

    return sessions


def _session_summary(viz: SessionVizData) -> dict[str, Any]:
    """Lightweight session summary for list views (no timeline)."""
    return {
        "session_id": viz.session_id,
        "title": viz.title,
        "workspace": viz.workspace,
        "model": viz.model,
        "provider": viz.provider,
        "status": viz.status,
        "agent_name": viz.agent_name,
        "start_time": viz.start_time,
        "end_time": viz.end_time,
        "duration_ms": viz.duration_ms,
        "turn_count": viz.turn_count,
        "tool_count": viz.tool_count,
        "tags": viz.tags,
    }


# ---------------------------------------------------------------------------
# Public: mount_viz() for F-82 future merge
# ---------------------------------------------------------------------------

def mount_viz(app: FastAPI, prefix: str = "/viz", **kwargs: Any) -> None:
    """Mount the Visualizer sub-app onto an existing FastAPI application.

    Usage::

        from extensions.visualizer.server import mount_viz
        mount_viz(main_app, prefix="/viz", allow_import=True)
    """
    viz_app = create_app(**kwargs)
    app.mount(prefix, viz_app)
