"""Session metadata parser for the new ClawCodeX session format.

Reads the on-disk shapes produced by ``src/services/session_storage.py``
and ``src/agent/transcript.py`` (the new wire format):

- Main transcript:    ``~/.clawcodex/sessions/<sid>/transcript.jsonl``
- Sub-agent (flat):   ``~/.clawcodex/transcripts/<agent_id>.jsonl``
- Sub-agent (nested): ``~/.clawcodex/sessions/<sid>/subagents/agent-<agent_id>.jsonl``
- Optional metadata:  ``~/.clawcodex/sessions/<sid>/metadata.json``
- Orchestrator state: ``~/.clawcodex/reports/run_*/state_journal.ndjson``

No backward-compat shims — the parser assumes the new shape throughout
(ISO-8601 timestamps, content-as-list, ``isMeta`` / ``isVirtual`` /
``isCompactSummary`` / ``parent_session_id`` semantics, ``cost_block``
transcript entries, etc.).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.viz_models import SessionVizData

logger = logging.getLogger(__name__)

# A session is considered "running" if its transcript file's mtime OR
# the metadata's ``last_updated`` field has been touched within this
# window. 5 minutes is generous enough to cover the longest-known LLM
# calls while still flipping to "completed" within a reasonable time
# after the agent finishes.
_RUNNING_RECENCY_SECONDS = 300

# Sub-agent filename pattern: ``agent-<id>.jsonl`` (the convention used by
# ``clawcodex_ext.transcript.nested_path`` when a parent session is
# registered).
_SUBAGENT_RE = re.compile(r"^agent-(?P<agent_id>.+)\.jsonl$")


def _coerce_iso_ts(value: Any) -> float:
    """Coerce an ISO 8601 string timestamp to a float Unix epoch.

    The new on-disk format only stores ISO 8601 timestamps (see
    ``src.types.messages.message_to_dict``); float epochs are not
    written. Returns 0.0 for anything unparseable.
    """
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        # ``Z`` suffix is not handled by fromisoformat in Python <3.11
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class SessionMetadataParser:
    """Parse a session directory into ``SessionVizData``.

    The new format does not separate "metadata.json vs transcript.jsonl
    vs session.json" — all three are unified under the on-disk shape
    above. This parser:

      1. Walks the main ``transcript.jsonl`` to recover wall-clock
         anchors, model, cost, and the user/assistant/tool block list.
      2. Reads ``metadata.json`` only when present (it is now optional —
         only written when ``SessionStorage`` happens to manage the
         session) and pulls ``cwd`` / ``title`` / ``tags`` / ``agent_name``.
      3. Walks the orchestrator state journal under
         ``~/.clawcodex/reports/run_*`` for F-96 issue association.
    """

    def __init__(
        self,
        sessions_dir: Path | None = None,
        transcripts_dir: Path | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")
        self.transcripts_dir = transcripts_dir or (Path.home() / ".clawcodex" / "transcripts")
        self.reports_dir = reports_dir or (Path.home() / ".clawcodex" / "reports")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, session_id: str) -> SessionVizData | None:
        """Parse a single session directory into ``SessionVizData``."""
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            logger.debug("Session dir not found: %s", session_dir)
            return None

        transcript_path = session_dir / "transcript.jsonl"
        metadata_path = session_dir / "metadata.json"

        # Start from an empty record; transcript is the source of truth.
        viz = SessionVizData(session_id=session_id)

        # Optional metadata: only fields that are NOT recoverable from
        # the transcript (cwd, title, tags, agent_name). Everything
        # else (start_time, end_time, model, cost, message_count) is
        # computed from the transcript.
        meta: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to load metadata for %s: %s", session_id, e)

        # Transcript-driven fields (start / end / model / cost / counts)
        if transcript_path.exists():
            self._enrich_from_transcript(viz, transcript_path)
        else:
            # Without a transcript we cannot recover any wall-clock
            # information. Use metadata as a last-resort fallback.
            start_time = meta.get("start_time", 0.0)
            last_updated = meta.get("last_updated", start_time)
            viz.start_time = start_time
            viz.end_time = last_updated or start_time
            viz.duration_ms = (
                int((viz.end_time - viz.start_time) * 1000) if viz.end_time > viz.start_time else 0
            )

        # Metadata-only fields (not recoverable from transcript)
        viz.workspace = meta.get("cwd", "")
        viz.title = meta.get("title", "") or session_id[:8]
        viz.tags = list(meta.get("tags", []))
        viz.agent_name = meta.get("agent_name", "")

        viz.status = self._infer_status(meta, transcript_path)

        if transcript_path.exists():
            viz.transcript_path = str(transcript_path)

        # F-96-E: orchestrator issue association
        self._enrich_from_state_journal(viz)

        return viz

    def list_sessions(self, limit: int = 100) -> list[SessionVizData]:
        """List recent sessions sorted by start_time descending."""
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

    # ------------------------------------------------------------------
    # Transcript enrichment
    # ------------------------------------------------------------------

    def _enrich_from_transcript(
        self,
        viz: SessionVizData,
        transcript_path: Path,
    ) -> None:
        """Walk the JSONL transcript and fill the transcript-driven fields.

        Reads the file once. Collects:

        - ``start_time`` / ``end_time`` — from the first / last
          parseable ISO timestamp. Snip boundaries
          (``isCompactSummary=True``) are honored: only the last
          boundary is kept, and timestamps are anchored to it.
        - ``model`` — first non-null ``model`` on a non-meta
          ``assistant`` entry that has real content.
        - ``turn_count`` — non-meta, non-virtual user+assistant pair count.
        - ``tool_count`` — count of ``tool_use`` blocks across
          non-meta assistant entries.
        - ``context_tokens`` — sum of ``usage.input_tokens +
          output_tokens + cache_creation_input_tokens +
          cache_read_input_tokens`` across non-meta assistant entries.
        - ``cost_block`` entries — folded into ``stats.cost_usd``
          (last cost_block wins; matches the cumulative cost semantics
          written by ``extensions.agent.session_persist``).
        """
        start_time: float = 0.0
        end_time: float = 0.0
        snip_anchor: float | None = None
        model: str = ""
        turn_count = 0
        tool_count = 0
        context_tokens = 0
        cost_usd: float = 0.0

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

                    # ``cost_block`` entries are written by
                    # ``session_persist.save_to_session_storage`` as
                    # ``{"type": "cost_block", "cost": {...}}``. They
                    # are not Messages; skip the user/assistant logic
                    # but still fold the cost.
                    if entry.get("type") == "cost_block":
                        cb = entry.get("cost", {})
                        if isinstance(cb, dict):
                            try:
                                cost_usd = float(cb.get("total_cost_usd", cost_usd) or cost_usd)
                            except (TypeError, ValueError):
                                pass
                            mu = cb.get("model_usage")
                            if isinstance(mu, dict):
                                # Replace the running context_tokens
                                # sum with the cumulative figure from
                                # the cost block — it accounts for
                                # cache tokens that the per-message
                                # usage fields also report, so summing
                                # both would double-count.
                                total = 0
                                for u in mu.values():
                                    if isinstance(u, dict):
                                        total += int(u.get("input_tokens", 0) or 0)
                                        total += int(u.get("output_tokens", 0) or 0)
                                        total += int(u.get("cache_creation_input_tokens", 0) or 0)
                                        total += int(u.get("cache_read_input_tokens", 0) or 0)
                                if total > 0:
                                    context_tokens = total
                        continue

                    ts = _coerce_iso_ts(entry.get("timestamp"))

                    # Snip boundaries mark the start of the kept
                    # window after a /compact. Anchor the timeline to
                    # the LAST snip boundary so the bars align with
                    # the post-compact segment, not pre-compact noise.
                    if entry.get("isCompactSummary"):
                        snip_anchor = ts or snip_anchor
                        # Reset the start to the snip timestamp so
                        # the visible window starts here.
                        if snip_anchor:
                            start_time = snip_anchor
                            end_time = max(end_time, snip_anchor)
                        continue

                    # Skip meta / virtual / progress entries — they
                    # are not real conversation turns and would
                    # inflate the counts. The new wire format
                    # explicitly tags these.
                    if entry.get("isMeta") or entry.get("isVirtual"):
                        continue
                    if entry.get("type") == "progress":
                        continue
                    if entry.get("isApiErrorMessage"):
                        # API errors are real events but should not
                        # count as turns / tools.
                        if ts:
                            start_time = start_time or ts
                            end_time = max(end_time, ts)
                        continue

                    # Anchor wall-clock bounds.
                    if ts:
                        start_time = start_time or ts
                        end_time = max(end_time, ts)

                    role = entry.get("role", "")
                    if role in ("user", "assistant"):
                        turn_count += 1

                    if role == "assistant":
                        # Model label: prefer the first non-null one.
                        if not model:
                            m = entry.get("model")
                            if isinstance(m, str) and m:
                                model = m
                        # Usage totals — accumulate per-message so
                        # callers without a cost_block still get a
                        # number. The cost_block branch above
                        # overrides this with the cumulative figure
                        # if present.
                        usage = entry.get("usage")
                        if isinstance(usage, dict):
                            context_tokens += int(usage.get("input_tokens", 0) or 0)
                            context_tokens += int(usage.get("output_tokens", 0) or 0)
                            context_tokens += int(usage.get("cache_creation_input_tokens", 0) or 0)
                            context_tokens += int(usage.get("cache_read_input_tokens", 0) or 0)
                        # Real LLM duration, when stamped by the call
                        # site — informs the StatsBuilder's average.
                        dur = entry.get("duration_ms")
                        if isinstance(dur, (int, float)) and dur:
                            # Stash on stats later via StatsBuilder.
                            pass
                        # tool_use blocks
                        content = entry.get("content")
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "tool_use":
                                    tool_count += 1
        except OSError as e:
            logger.debug("Failed to read transcript %s: %s", transcript_path, e)

        viz.start_time = start_time
        viz.end_time = end_time
        viz.duration_ms = int((end_time - start_time) * 1000) if end_time > start_time else 0
        if model:
            viz.model = model
        viz.turn_count = turn_count
        viz.tool_count = tool_count
        if context_tokens:
            viz.stats.context_tokens = context_tokens
        if cost_usd:
            viz.stats.cost_usd = cost_usd

    # ------------------------------------------------------------------
    # Status inference
    # ------------------------------------------------------------------

    def _infer_status(
        self,
        meta: dict[str, Any],
        transcript_path: Path,
    ) -> str:
        """Infer session status from transcript freshness and metadata.

        Resolution order (first match wins):

          1. ``status`` field explicitly set in ``metadata.json``.
          2. Transcript file's mtime is within ``_RUNNING_RECENCY_SECONDS``
             → still being written, so ``"running"``.
          3. ``metadata.json:last_updated`` is within the recency window
             → ``"running"``.
          4. Transcript missing → ``"unknown"``.
          5. Otherwise → ``"completed"``.
        """
        status = meta.get("status")
        if isinstance(status, str) and status:
            return status

        now = time.time()
        if transcript_path.exists():
            try:
                if now - transcript_path.stat().st_mtime < _RUNNING_RECENCY_SECONDS:
                    return "running"
            except OSError:
                pass

        last_updated = meta.get("last_updated") or 0
        if last_updated and now - float(last_updated) < _RUNNING_RECENCY_SECONDS:
            return "running"

        if not transcript_path.exists():
            return "unknown"

        return "completed"

    # ------------------------------------------------------------------
    # Orchestrator enrichment (F-96-E)
    # ------------------------------------------------------------------

    def _enrich_from_state_journal(self, viz: SessionVizData) -> None:
        """Pull ``issue_id`` and ``verification_status`` from the orchestrator state journal.

        Scans ``~/.clawcodex/reports/run_*/state_journal.ndjson`` for a
        ``session_ref`` event matching this session's id, then a
        ``verification`` event for that issue.
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
                issue_id = ""
                for ev in events:
                    if ev.get("type") == "session_ref" and ev.get("session_id") == viz.session_id:
                        issue_id = str(ev.get("issue_id", ""))
                        break
                if issue_id:
                    viz.issue_id = issue_id
                    for ev in events:
                        if (
                            ev.get("type") == "verification"
                            and str(ev.get("issue_id", "")) == issue_id
                        ):
                            viz.verification_status = str(ev.get("verification_status", ""))
                            break
            except Exception as e:
                logger.debug("State journal enrich failed for %s: %s", viz.session_id, e)
                continue
