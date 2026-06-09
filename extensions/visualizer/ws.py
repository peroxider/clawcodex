"""WebSocket live tail for session events (F-92-B).

Provides real-time push of new TimelineBar entries as a session runs.
Connect to ``/api/viz/ws/sessions/{session_id}``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class SessionLiveTail:
    """Manages WebSocket connections and file tailing for a session."""

    def __init__(self, session_id: str, transcript_path: Path | None = None) -> None:
        self.session_id = session_id
        self.transcript_path = transcript_path
        self.connections: list[WebSocket] = []
        self._last_offset = 0
        self._running = False

    async def add_connection(self, ws: WebSocket) -> None:
        """Register a WebSocket client."""
        await ws.accept()
        self.connections.append(ws)
        logger.debug("WS client connected for session %s (%d clients)", self.session_id, len(self.connections))

    def remove_connection(self, ws: WebSocket) -> None:
        """Unregister a WebSocket client."""
        if ws in self.connections:
            self.connections.remove(ws)
        logger.debug("WS client disconnected for session %s (%d clients)", self.session_id, len(self.connections))

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send an event to all connected clients."""
        payload = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_connection(ws)

    async def tail_loop(self, interval: float = 1.0) -> None:
        """Poll the transcript file for new lines and broadcast them."""
        self._running = True
        while self._running and self.transcript_path and self.transcript_path.exists():
            try:
                with open(self.transcript_path, "r", encoding="utf-8") as f:
                    f.seek(self._last_offset)
                    new_lines = f.readlines()
                    self._last_offset = f.tell()

                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        await self.broadcast({
                            "type": "transcript_event",
                            "session_id": self.session_id,
                            "data": entry,
                            "timestamp": time.time(),
                        })
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON line in transcript tail")
            except Exception:
                logger.debug("Error tailing transcript for %s", self.session_id, exc_info=True)

            await asyncio.sleep(interval)

    def stop(self) -> None:
        """Signal the tail loop to stop."""
        self._running = False


# Global registry of active live tails
_active_tails: dict[str, SessionLiveTail] = {}


def create_ws_router() -> APIRouter:
    """Create the WebSocket router for live tailing sessions."""
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def ws_session_live(websocket: WebSocket, session_id: str) -> None:
        """WebSocket endpoint for live-tailing a session's transcript."""
        # Resolve transcript path
        from .server import _AppState
        app = websocket.app
        state: _AppState = app.state.viz

        # Try to find the transcript file
        transcript_path: Path | None = None
        session_dir = state.sessions_dir / session_id
        if session_dir.is_dir():
            tp = session_dir / "transcript.jsonl"
            if tp.exists():
                transcript_path = tp

        # Get or create the live tail
        if session_id not in _active_tails:
            tail = SessionLiveTail(session_id, transcript_path)
            _active_tails[session_id] = tail
            # Start tailing in background
            asyncio.create_task(tail.tail_loop())
        else:
            tail = _active_tails[session_id]
            # Update transcript path if resolved
            if transcript_path and not tail.transcript_path:
                tail.transcript_path = transcript_path

        # Accept and register
        await tail.add_connection(websocket)
        try:
            # Keep connection alive — client disconnects cause WebSocketDisconnect
            while True:
                # Receive pings / client messages (optional heartbeat)
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    # Send heartbeat
                    try:
                        await websocket.send_text(json.dumps({"type": "heartbeat", "timestamp": time.time()}))
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            tail.remove_connection(websocket)
            # Cleanup idle tails
            if not tail.connections:
                tail.stop()
                _active_tails.pop(session_id, None)

    return router
