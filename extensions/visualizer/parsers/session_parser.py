"""Session metadata parser (F-91-B).

Reads SessionStorage metadata.json and RunReport JSON to produce
SessionVizData with basic fields populated.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ..models.viz_models import SessionVizData, OperationStats

logger = logging.getLogger(__name__)

# A session is considered "running" if either the transcript file's
# mtime OR the metadata's ``last_updated`` field has been touched within
# this window. 5 minutes is generous enough to cover the longest-known
# LLM calls while still flipping a session to "completed" within a
# reasonable time after the agent finishes.
_RUNNING_RECENCY_SECONDS = 300


class SessionMetadataParser:
    """Parse session metadata from SessionStorage directories."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")

    def parse(self, session_id: str) -> SessionVizData | None:
        """Parse a single session directory into SessionVizData."""
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            logger.debug("Session dir not found: %s", session_dir)
            return None

        metadata_path = session_dir / "metadata.json"
        transcript_path = session_dir / "transcript.jsonl"
        snapshot_path = session_dir / f"{session_id}.json"

        # Load metadata
        meta: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to load metadata for %s: %s", session_id, e)

        # Build base SessionVizData
        start_time = meta.get("start_time", 0.0)
        last_updated = meta.get("last_updated", start_time)
        duration_ms = int((last_updated - start_time) * 1000) if last_updated > start_time else 0

        viz = SessionVizData(
            session_id=session_id,
            title=meta.get("title", "") or session_id[:8],
            workspace=meta.get("cwd", ""),
            model=meta.get("model", ""),
            start_time=start_time,
            end_time=last_updated,
            duration_ms=duration_ms,
            status=self._infer_status(meta, transcript_path),
            agent_name=meta.get("agent_name", ""),
            tags=meta.get("tags", []),
            transcript_path=str(transcript_path) if transcript_path.exists() else None,
            snapshot_path=str(snapshot_path) if snapshot_path.exists() else None,
            turn_count=meta.get("message_count", 0),
            detected_mode=meta.get("detected_mode", ""),
            config_summary=meta.get("config", {}),
        )

        # Try to enrich from snapshot JSON
        self._enrich_from_snapshot(viz, snapshot_path)
        # Try to enrich from RunReport JSON in reports dir
        self._enrich_from_report(viz, session_id)

        return viz

    def list_sessions(self, limit: int = 100) -> list[SessionVizData]:
        """List recent sessions sorted by last_updated descending."""
        results: list[SessionVizData] = []
        if not self.sessions_dir.exists():
            return results

        for entry in self.sessions_dir.iterdir():
            if not entry.is_dir():
                continue
            sid = entry.name
            viz = self.parse(sid)
            if viz is not None:
                results.append(viz)

        results.sort(key=lambda v: v.start_time or 0, reverse=True)
        return results[:limit]

    def _infer_status(self, meta: dict[str, Any], transcript_path: Path) -> str:
        """Infer session status from metadata and transcript freshness.

        Resolution order (first match wins):
          1. ``status`` field explicitly set in metadata.
          2. Transcript file's mtime is within ``_RUNNING_RECENCY_SECONDS``
             → still being written, so ``"running"``.
          3. ``last_updated`` is within ``_RUNNING_RECENCY_SECONDS``
             → metadata is being kept fresh, so ``"running"``.
          4. Transcript missing entirely → ``"unknown"`` (agent may be
             in the brief window between metadata creation and first
             tool call; polling will flip it to ``running`` once
             activity shows up).
          5. Otherwise → ``"completed"``.

        The recency check is what makes the live poll useful: a session
        that started an hour ago but is still actively running (e.g. a
        long workflow with a live orchestrator) correctly shows
        ``"running"`` instead of being mis-classified as
        ``"completed"`` just because ``last > start + 5``.
        """
        if meta.get("status"):
            return str(meta["status"])

        now = time.time()
        if transcript_path.exists():
            try:
                if now - transcript_path.stat().st_mtime < _RUNNING_RECENCY_SECONDS:
                    return "running"
            except OSError:
                pass
        last_updated = meta.get("last_updated") or 0
        if last_updated and now - last_updated < _RUNNING_RECENCY_SECONDS:
            return "running"
        if not transcript_path.exists():
            return "unknown"
        start = meta.get("start_time", 0)
        last = last_updated or start
        if last > start + 5:  # at least 5 seconds of activity
            return "completed"
        return "running"

    def _enrich_from_snapshot(self, viz: SessionVizData, snapshot_path: Path) -> None:
        """Enrich viz data from the F-49 .json snapshot."""
        if not snapshot_path.exists():
            return
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            cost = data.get("cost", {})
            if cost:
                viz.stats.cost_usd = cost.get("total_cost_usd", 0.0)
                viz.stats.context_tokens = sum(
                    u.get("input_tokens", 0) + u.get("output_tokens", 0)
                    for u in cost.get("model_usage", {}).values()
                )
            viz.provider = data.get("provider", viz.provider)
            viz.model = data.get("model", viz.model)
            # Count turns from conversation if available
            conv = data.get("conversation", {})
            msgs = conv.get("messages", [])
            if msgs:
                viz.turn_count = len(msgs)
        except Exception as e:
            logger.debug("Snapshot enrich failed for %s: %s", viz.session_id, e)

    def _enrich_from_report(self, viz: SessionVizData, session_id: str) -> None:
        """Enrich from RunReport JSON in persistent reports dir."""
        # Search in ~/.clawcodex/reports/*/*/*/
        reports_root = Path.home() / ".clawcodex" / "reports"
        if not reports_root.exists():
            return
        # Look for {session_id}.json in any subdir
        for report_json in reports_root.rglob(f"{session_id}.json"):
            try:
                data = json.loads(report_json.read_text(encoding="utf-8"))
                viz.tool_count = data.get("tool_count", viz.tool_count)
                viz.turn_count = data.get("turn_count", viz.turn_count)
                viz.status = data.get("status", viz.status).lower()
                viz.report_path = str(report_json.with_suffix(".md"))
                viz.tool_events_path = data.get("tool_events_path")
                viz.end_reason = data.get("session_end_reason")
                viz.end_summary = data.get("session_end_summary", "")
            except Exception as e:
                logger.debug("Report enrich failed for %s: %s", session_id, e)
