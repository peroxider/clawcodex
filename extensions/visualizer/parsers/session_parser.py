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

    def __init__(self, sessions_dir: Path | None = None, reports_dir: Path | None = None) -> None:
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")
        self.reports_dir = reports_dir or (self.sessions_dir.parent / ".reports")

    def parse(self, session_id: str) -> SessionVizData | None:
        """Parse a single session directory into SessionVizData."""
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            logger.debug("Session dir not found: %s", session_dir)
            return None

        metadata_path = session_dir / "metadata.json"
        transcript_path = session_dir / "transcript.jsonl"
        snapshot_path = session_dir / f"{session_id}.json"
        # F-91-B 补遗: Session.save() 和 AgentSession._save_json_snapshot()
        # 将快照写入 ~/.clawcodex/sessions/{session_id}.json (sessions 根目录),
        # 而非 SessionStorage 的子目录 {session_id}/{session_id}.json。
        # 所以当子目录路径找不到时，回退到 sessions 根目录查找。
        if not snapshot_path.exists():
            alt_snapshot_path = self.sessions_dir / f"{session_id}.json"
            if alt_snapshot_path.exists():
                snapshot_path = alt_snapshot_path

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
        # Prefer an explicit ``end_time`` in the metadata (the wall-clock end
        # the session actually ran to). Fall back to ``last_updated``, which
        # tracks writes to the metadata file itself (and is missing from many
        # fixtures / imports, in which case it defaulted to ``start_time``
        # — silently yielding ``duration_ms = 0`` and a zero-width gantt).
        end_time = meta.get("end_time") or last_updated
        duration_ms = int((end_time - start_time) * 1000) if end_time > start_time else 0

        # Backfill start_time from the transcript when metadata is clock-skewed.
        # Common when the agent loop creates metadata at session start but the
        # first user message has an earlier wall-clock timestamp (e.g. resume
        # paths, batch imports, or test fixtures). Without this, the
        # waterfall's ``rel()`` clamps every bar to x=0, collapsing the
        # chart onto a single pixel. See git blame for screenshot repro
        # (session 02cba64e-… : start_time 15:19:31 vs transcript 15:16:48).
        if transcript_path.exists():
            transcript_min_ts = self._transcript_min_timestamp(transcript_path)
            if transcript_min_ts and (start_time <= 0 or transcript_min_ts < start_time):
                anchor_end = end_time if end_time and end_time > transcript_min_ts else transcript_min_ts
                duration_ms = max(0, int((anchor_end - transcript_min_ts) * 1000))
                start_time = transcript_min_ts

        # ``turn_count``: prefer explicit field; fall back to message_count for
        # older metadata that used the older key. ``tool_count`` is enriched
        # from the snapshot / run report below.
        turn_count = meta.get("turn_count", 0) or meta.get("message_count", 0)

        viz = SessionVizData(
            session_id=session_id,
            title=meta.get("title", "") or session_id[:8],
            workspace=meta.get("cwd", ""),
            model=meta.get("model", ""),
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            status=self._infer_status(meta, transcript_path),
            agent_name=meta.get("agent_name", ""),
            tags=meta.get("tags", []),
            transcript_path=str(transcript_path) if transcript_path.exists() else None,
            snapshot_path=str(snapshot_path) if snapshot_path.exists() else None,
            turn_count=turn_count,
            tool_count=meta.get("tool_count", 0),
            detected_mode=meta.get("detected_mode", ""),
            config_summary=meta.get("config", {}),
        )

        # Try to enrich from snapshot JSON
        self._enrich_from_snapshot(viz, snapshot_path)
        # Try to enrich from RunReport JSON in reports dir
        self._enrich_from_report(viz, session_id)
        # F-96-E: Enrich from orchestrator state journal (issue_id, verification_status)
        self._enrich_from_state_journal(viz)

        # Lowest-priority fallback: context_tokens from metadata.json
        if not viz.stats.context_tokens:
            viz.stats.context_tokens = meta.get("totalContextTokens", 0) or meta.get("context_tokens", 0)

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
        # Stale session with a transcript: the agent is done. Covers
        # both long sessions and short ones that died fast — neither
        # should be reported as "running" once the recency window
        # has passed. (The old "last < start + 5" branch returned
        # "running" and mis-classified sessions like
        # run-01-20260608... that hit a 429 rate limit 27 ms after
        # start, leaving last_updated ≈ start_time.)
        return "completed"

    def _enrich_from_snapshot(self, viz: SessionVizData, snapshot_path: Path) -> None:
        """Enrich viz data from the F-49 .json snapshot."""
        if not snapshot_path.exists():
            return
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            cost = data.get("cost", {})
            if cost:
                viz.stats.cost_usd = cost.get("total_cost_usd", 0.0)
                cost_model_usage = cost.get("model_usage", {})
                if cost_model_usage:
                    viz.stats.context_tokens = sum(
                        u.get("input_tokens", 0) + u.get("output_tokens", 0) +
                        u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                        for u in cost_model_usage.values()
                    )
                # Fallback: if model_usage was empty, try top-level totalContextTokens
                if not viz.stats.context_tokens and data.get("totalContextTokens"):
                    viz.stats.context_tokens = int(data["totalContextTokens"])
            viz.provider = data.get("provider", viz.provider)
            viz.model = data.get("model", viz.model)
            # Count turns from conversation if available
            conv = data.get("conversation", {})
            msgs = conv.get("messages", [])
            if msgs:
                viz.turn_count = len(msgs)
                # Count tool_use blocks across all messages for tool_count
                tool_count = 0
                for msg in msgs:
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_count += 1
                if tool_count:
                    viz.tool_count = tool_count
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
                viz.stats.context_tokens = data.get("context_tokens", viz.stats.context_tokens)
                viz.end_reason = data.get("session_end_reason")
                viz.end_summary = data.get("session_end_summary", "")
            except Exception as e:
                logger.debug("Report enrich failed for %s: %s", session_id, e)

    def _enrich_from_state_journal(self, viz: SessionVizData) -> None:
        """F-96-E: Enrich session viz data from orchestrator state journal.

        Scans ``.reports/run_*/state_journal.ndjson`` for a ``session_ref``
        event matching this session_id, then pulls the associated
        ``issue_id`` and ``verification_status``.
        """
        if not self.reports_dir.exists():
            return
        for run_dir in sorted(self.reports_dir.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                continue
            journal = run_dir / "state_journal.ndjson"
            if not journal.exists():
                continue
            try:
                events: list[dict[str, Any]] = []
                with open(journal, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                # Find session_ref matching this session_id
                issue_id = ""
                for ev in events:
                    if ev.get("type") == "session_ref" and ev.get("session_id") == viz.session_id:
                        issue_id = ev.get("issue_id", "")
                        break
                if issue_id:
                    viz.issue_id = str(issue_id)
                    # Look for verification event for this issue
                    for ev in events:
                        if ev.get("type") == "verification" and str(ev.get("issue_id", "")) == issue_id:
                            viz.verification_status = ev.get("verification_status", "")
                            break
            except Exception as e:
                logger.debug("State journal enrich failed for %s: %s", viz.session_id, e)

    @staticmethod
    def _transcript_min_timestamp(transcript_path: Path) -> float:
        """Return the smallest parseable timestamp across the transcript.

        Used to backfill ``start_time`` when metadata is clock-skewed.
        Supports both numeric (``_timestamp`` / ``timestamp``) and ISO 8601
        string forms; lines without a parseable timestamp are skipped.
        Returns 0.0 when no usable timestamp is found.
        """
        from datetime import datetime

        def _coerce(value: Any) -> float:
            if value is None:
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    return 0.0
            return 0.0

        best = float("inf")
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    ts = _coerce(entry.get("_timestamp")) or _coerce(entry.get("timestamp"))
                    if 0 < ts < best:
                        best = ts
        except OSError as e:
            logger.debug("Could not read transcript %s: %s", transcript_path, e)
            return 0.0
        return 0.0 if best == float("inf") else best
