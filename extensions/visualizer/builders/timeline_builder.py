"""Timeline builder (F-91-C).

Aggregates TimelineBar objects from multiple parsers into a unified timeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..models.viz_models import SessionVizData, TimelineBar
from ..parsers.session_parser import SessionMetadataParser
from ..parsers.transcript_parser import TranscriptParser
from ..parsers.tool_events_parser import ToolEventsParser
from ..parsers.multi_agent_parser import MultiAgentParser

logger = logging.getLogger(__name__)


class TimelineBuilder:
    """Build a unified timeline for a session by combining all data sources."""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        transcripts_dir: Path | None = None,
        reports_dir: Path | None = None,
    ) -> None:
        self.session_parser = SessionMetadataParser(
            sessions_dir=sessions_dir,
            transcripts_dir=transcripts_dir,
            reports_dir=reports_dir,
        )
        self.transcript_parser = TranscriptParser()
        self.tool_events_parser = ToolEventsParser()
        self.multi_agent_parser = MultiAgentParser()
        self.sessions_dir = sessions_dir or (Path.home() / ".clawcodex" / "sessions")
        self.transcripts_dir = transcripts_dir or (Path.home() / ".clawcodex" / "transcripts")

    def build(self, session_id: str) -> SessionVizData | None:
        """Build complete SessionVizData for a session."""
        # Parse base metadata
        viz = self.session_parser.parse(session_id)
        if viz is None:
            return None

        # Parse transcript bars
        if viz.transcript_path:
            transcript_bars = self.transcript_parser.parse_file(viz.transcript_path)
            viz.timeline.extend(transcript_bars)

        # Parse tool events bars
        if viz.tool_events_path:
            tool_bars = self.tool_events_parser.parse_file(viz.tool_events_path)
            viz.timeline.extend(tool_bars)

        # Parse agent tree — discover sub-agents from the new layout
        # (flat ``~/.clawcodex/transcripts/*.jsonl`` and nested
        # ``sessions/<sid>/subagents/agent-*.jsonl``). The legacy
        # ``.orchestrator_control/runs/<rid>/agent_meta.json`` tree has
        # been replaced.
        agent_tree = self.multi_agent_parser.parse_for_session(
            session_id,
            sessions_dir=self.sessions_dir,
            transcripts_dir=self.transcripts_dir,
        )
        viz.agent_tree = agent_tree

        # Sort timeline by start time
        viz.timeline.sort(key=lambda b: b.start_time)

        # Compute stats — pass the pre-enriched ``viz.stats`` as a base so
        # cost_usd / context_tokens populated by ``_enrich_from_transcript``
        # survive the recomputation. Without this, the enrichment is
        # silently wiped every time.
        from .stats_builder import StatsBuilder
        viz.stats = StatsBuilder().build(viz.timeline, base=viz.stats)

        # Detect anomalies
        from .anomaly_builder import AnomalyBuilder
        viz.anomalies = AnomalyBuilder().build(viz)

        # Compute multi-agent waterfall layout (spawn_x / join_x / depth_y).
        # Best-effort: never raises — if the timeline has no Agent calls,
        # the layout is a no-op and agent_layout_summary stays empty.
        from .agent_tree_layout import AgentTreeLayout
        try:
            AgentTreeLayout().layout(viz)
        except Exception as e:
            logger.debug("AgentTreeLayout failed for %s: %s", session_id, e)

        return viz

    def build_for_sessions(self, session_ids: list[str]) -> list[SessionVizData]:
        """Build viz data for multiple sessions."""
        results: list[SessionVizData] = []
        for sid in session_ids:
            viz = self.build(sid)
            if viz:
                results.append(viz)
        return results
