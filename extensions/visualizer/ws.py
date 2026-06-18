"""WebSocket live tail for session events (F-92-B).

Provides real-time push of new TimelineBar entries as a session runs.
Connect to ``/api/viz/ws/sessions/{session_id}``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .builders.operation_categorizer import OperationCategorizer
from .models.viz_models import BarType, TimelineBar

logger = logging.getLogger(__name__)


class SessionLiveTail:
    """Manages WebSocket connections and file tailing for a session."""

    def __init__(self, session_id: str, transcript_path: Path | None = None) -> None:
        self.session_id = session_id
        self.transcript_path = transcript_path
        self.connections: list[WebSocket] = []
        self._last_offset = 0
        self._running = False
        # tool_use_id → bar dict; lets tool_result updates find their
        # corresponding tool_use so the client can mutate (not duplicate)
        # the tick in the chart.
        self._pending_tools: dict[str, dict[str, Any]] = {}
        # Reused across the lifetime of the tail — pure, no I/O.
        self._categorizer = OperationCategorizer()

    # Tool color palette mirrors transcript_parser._TOOL_COLORS so the
    # live stream and the static parser agree on color → category.
    _TOOL_COLORS: dict[str, str] = {
        "Read": "#5470c6",
        "Write": "#91cc75",
        "Edit": "#fac858",
        "Bash": "#ee6666",
        "Grep": "#73c0de",
        "Glob": "#3ba272",
        "WebFetch": "#fc8452",
        "WebSearch": "#9a60b4",
        "TodoWrite": "#ea7ccc",
        "TaskStop": "#ff9f7f",
    }

    @staticmethod
    def _coerce_ts(value: Any) -> float:
        """Coerce a transcript timestamp to a float Unix epoch.

        Accepts float / int / ISO 8601 string / ``None`` — mirrors
        ``transcript_parser._coerce_timestamp`` to avoid an import cycle.
        """
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0
        return 0.0

    async def add_connection(self, ws: WebSocket) -> None:
        """Register a WebSocket client."""
        await ws.accept()
        self.connections.append(ws)
        logger.debug(
            "WS client connected for session %s (%d clients)",
            self.session_id,
            len(self.connections),
        )

    def remove_connection(self, ws: WebSocket) -> None:
        """Unregister a WebSocket client."""
        if ws in self.connections:
            self.connections.remove(ws)
        logger.debug(
            "WS client disconnected for session %s (%d clients)",
            self.session_id,
            len(self.connections),
        )

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
        """Poll the transcript file for new lines and broadcast them.

        Emits two event types per new line:

        * ``transcript_event`` — the raw JSONL entry, kept for backward
          compat with the Gantt view's full-reload strategy.
        * ``bar_update`` — a pre-classified TimelineBar-like payload
          (id / start_time / end_time / category / color / status). The
          waterfall view mutates an existing tick in place on receipt,
          which avoids the cost of a server round-trip per event.
        """
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
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON line in transcript tail")
                        continue

                    emit_ts = time.time()
                    # Backward-compat event for Gantt view.
                    await self.broadcast(
                        {
                            "type": "transcript_event",
                            "session_id": self.session_id,
                            "data": entry,
                            "timestamp": emit_ts,
                        }
                    )
                    # Structured update for the waterfall view.
                    update = self._entry_to_bar_update(entry, emit_ts)
                    if update is not None:
                        await self.broadcast(update)
            except Exception:
                logger.debug("Error tailing transcript for %s", self.session_id, exc_info=True)

            await asyncio.sleep(interval)

    def _entry_to_bar_update(
        self,
        entry: dict[str, Any],
        emit_ts: float,
    ) -> dict[str, Any] | None:
        """Convert a single JSONL entry to a ``bar_update`` event, or ``None``.

        Handles two block types:

        * ``tool_use`` — registers a pending bar in ``self._pending_tools``
          keyed by ``tool_use_id`` and emits status="running".
        * ``tool_result`` — looks up the pending bar by ``tool_use_id``,
          updates its ``end_time`` and ``status`` ("success" / "error").

        All other blocks (text, system, etc.) return ``None`` so the
        waterfall view stays focused on tool activity.
        """
        role = entry.get("role", "")
        if role not in ("assistant", "user"):
            return None
        content = entry.get("content")
        if not isinstance(content, list):
            return None
        timestamp = self._coerce_ts(entry.get("_timestamp") or entry.get("timestamp"))

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "tool_use":
                tool_use_id = block.get("tool_use_id") or f"tu-{emit_ts}"
                tool_name = block.get("name", "unknown")
                is_agent = bool(
                    block.get("isAgentInvocation")
                    or block.get("is_agent_invocation")
                    or tool_name in ("Agent", "Task", "SendMessage", "TeamCreate")
                )
                mini_bar = TimelineBar(
                    id=tool_use_id,
                    type=BarType.TOOL_CALL,
                    label=tool_name,
                    start_time=timestamp,
                    end_time=timestamp,
                    duration_ms=0,
                    status="running",
                    detail={
                        "tool_name": tool_name,
                        "isAgentInvocation": is_agent,
                    },
                )
                category = self._categorizer.categorize(mini_bar)
                color = self._TOOL_COLORS.get(tool_name) or category.color
                bar = {
                    "id": tool_use_id,
                    "tool_name": tool_name,
                    "label": tool_name,
                    "start_time": timestamp,
                    "end_time": timestamp,
                    "category": category.value,
                    "color": color,
                    "status": "running",
                }
                self._pending_tools[tool_use_id] = bar
                return {
                    "type": "bar_update",
                    "session_id": self.session_id,
                    "bar": bar,
                    "timestamp": emit_ts,
                }
            if btype == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                pending = self._pending_tools.pop(tool_use_id, None)
                is_error = bool(block.get("is_error"))
                status = "error" if is_error else "success"
                if pending is None:
                    # Orphan result (no matching tool_use) — synthesize a
                    # minimal bar so the client at least shows the event.
                    pending = {
                        "id": tool_use_id or f"tr-{emit_ts}",
                        "tool_name": "result",
                        "label": "result",
                        "start_time": timestamp,
                        "end_time": timestamp,
                        "category": "other",
                        "color": "#a0a0b0",
                        "status": status,
                    }
                else:
                    pending["end_time"] = timestamp
                    pending["status"] = status
                return {
                    "type": "bar_update",
                    "session_id": self.session_id,
                    "bar": pending,
                    "timestamp": emit_ts,
                }
        return None

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

        # The main session transcript is at
        # ``<sessions_dir>/<session_id>/transcript.jsonl`` (same path
        # in the new format).
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
                        await websocket.send_text(
                            json.dumps({"type": "heartbeat", "timestamp": time.time()})
                        )
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


# ---------------------------------------------------------------------------
# F-96-E: Orchestrator State Journal live tail
# ---------------------------------------------------------------------------


class OrchestratorJournalTail:
    """Tails a state_journal.ndjson file and broadcasts events via WebSocket.

    Similar to ``SessionLiveTail`` but reads orchestrator state journal
    events instead of transcript entries.
    """

    def __init__(self, journal_path: Path) -> None:
        self.journal_path = journal_path
        self.connections: list[WebSocket] = []
        self._last_offset = 0
        self._running = False

    async def add_connection(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)
        logger.debug(
            "Orch WS client connected for journal %s (%d clients)",
            self.journal_path,
            len(self.connections),
        )

    def remove_connection(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)
        logger.debug(
            "Orch WS client disconnected (%d remaining)",
            len(self.connections),
        )

    async def broadcast(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_connection(ws)

    async def tail_loop(self, interval: float = 1.5) -> None:
        """Poll the journal file for new events and broadcast them."""
        self._running = True
        while self._running and self.journal_path.exists():
            try:
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    f.seek(self._last_offset)
                    new_lines = f.readlines()
                    self._last_offset = f.tell()

                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    await self.broadcast(
                        {
                            "type": "orchestrator_event",
                            "data": entry,
                            "timestamp": time.time(),
                        }
                    )
            except Exception:
                logger.debug(
                    "Error tailing orchestrator journal",
                    exc_info=True,
                )
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False


_active_orch_tails: dict[str, OrchestratorJournalTail] = {}


def create_orch_ws_router() -> APIRouter:
    """Create the WebSocket router for orchestrator state journal tailing (F-96-E)."""
    router = APIRouter()

    @router.websocket("/ws/orchestrator/{run_id}")
    async def ws_orchestrator_live(websocket: WebSocket, run_id: str) -> None:
        """WebSocket endpoint for live-tailing an orchestrator run's state journal."""
        from .server import _AppState

        app = websocket.app
        state: _AppState = app.state.viz

        # New-format reports dir: ``~/.clawcodex/reports/<run_id>/...``
        reports_dir = state.reports_dir
        journal_path: Path | None = None
        if reports_dir:
            journal_path = reports_dir / run_id / "state_journal.ndjson"

        if not journal_path or not journal_path.exists():
            await websocket.close(code=404, reason="Journal not found")
            return

        # Get or create tail
        if run_id not in _active_orch_tails:
            tail = OrchestratorJournalTail(journal_path)
            _active_orch_tails[run_id] = tail
            asyncio.create_task(tail.tail_loop())
        else:
            tail = _active_orch_tails[run_id]

        await tail.add_connection(websocket)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30.0,
                    )
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    try:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "heartbeat",
                                    "timestamp": time.time(),
                                }
                            )
                        )
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            tail.remove_connection(websocket)
            if not tail.connections:
                tail.stop()
                _active_orch_tails.pop(run_id, None)

    return router
