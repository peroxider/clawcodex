"""Session metadata parser (F-91-B).

Reads SessionStorage metadata.json and RunReport JSON to produce
SessionVizData with basic fields populated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import SessionVizData, OperationStats

logger = logging.getLogger(__name__)


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
        """Infer session status from metadata and transcript existence."""
        if meta.get("status"):
            return meta["status"]
        if not transcript_path.exists():
            return "unknown"
        # If transcript exists but no explicit status, assume completed
        # if last_updated is significantly after start_time
        start = meta.get("start_time", 0)
        last = meta.get("last_updated", 0)
        if last > start + 5:  # at least 5 seconds elapsed
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
