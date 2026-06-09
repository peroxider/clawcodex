"""Conditional session import router (F-92-C).

Only mounted when ``--allow-import`` flag is set.
Provides endpoints for importing external session data via URL,
with SSRF protection.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_host(hostname: str) -> bool:
    """Check if a hostname resolves to a private IP address."""
    import socket
    try:
        addrinfo = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _type, _proto, _canonname, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for network in _PRIVATE_NETWORKS:
                    if ip in network:
                        return True
            except ValueError:
                continue
    except socket.gaierror:
        # If we can't resolve it, treat it as potentially dangerous
        return True
    return False


def _validate_import_url(url: str) -> str:
    """Validate a URL for import, raising on SSRF risk."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs allowed, got: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")
    if _is_private_host(parsed.hostname):
        raise ValueError(f"Import from private/local network not allowed: {parsed.hostname}")
    return url


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ImportRequest(BaseModel):
    """Request body for session import."""

    url: str = Field(description="URL to import session data from")
    workspace_id: str | None = Field(default=None, description="Target workspace ID")
    format: str = Field(default="json", description="Source format (json, jsonl)")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def create_import_router() -> APIRouter:
    """Create the conditional import router."""
    router = APIRouter(prefix="/import", tags=["import"])

    @router.post("", status_code=202)
    async def start_import(request: Request, body: ImportRequest):
        """Start an async import job (conditional — only when allow_import=True)."""
        from .server import _AppState
        state: _AppState = request.app.state.viz

        if not state.allow_import:
            raise HTTPException(status_code=403, detail="Import is not enabled. Use --allow-import flag.")

        # SSRF check
        try:
            safe_url = _validate_import_url(body.url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Create async task
        task_id = uuid.uuid4().hex[:12]
        from .models.viz_models import ImportStatus
        status = ImportStatus(task_id=task_id, status="pending")
        state.import_tasks[task_id] = status

        # Run import in background
        asyncio.create_task(_do_import(state, task_id, safe_url, body))

        return {"task_id": task_id, "status": "pending"}

    @router.get("/status/{task_id}")
    async def get_import_status(request: Request, task_id: str):
        """Check the status of an import job."""
        from .server import _AppState
        state: _AppState = request.app.state.viz
        status = state.import_tasks.get(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Import task not found")
        return status

    return router


# ---------------------------------------------------------------------------
# Background import logic
# ---------------------------------------------------------------------------

async def _do_import(state: Any, task_id: str, url: str, body: ImportRequest) -> None:
    """Execute the actual import in the background."""
    import_status = state.import_tasks[task_id]
    import_status.status = "running"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.text

        import_status.progress = 50

        # Save to sessions dir
        session_id = f"imported-{task_id}"
        session_dir = state.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        if body.format == "jsonl":
            # Save as transcript.jsonl
            (session_dir / "transcript.jsonl").write_text(data, encoding="utf-8")
        else:
            # Save as metadata.json
            (session_dir / "metadata.json").write_text(data, encoding="utf-8")

        import_status.status = "completed"
        import_status.progress = 100
        import_status.result = {"session_id": session_id, "path": str(session_dir)}

    except Exception as e:
        logger.error("Import failed for task %s: %s", task_id, e)
        import_status.status = "failed"
        import_status.error = str(e)
