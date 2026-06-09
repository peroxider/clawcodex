"""Timeline builder (F-91-C).

Aggregates TimelineBar objects from multiple parsers into a unified timeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models.viz_models import SessionVizData, TimelineBar
from ..parsers.session_parser import SessionMetadataParser
from ..parsers.transcript_parser import TranscriptParser
from ..parsers.tool_events_parser import ToolEventsParser
from ..parsers.multi_agent_parser import MultiAgentParser


class TimelineBuilder:
    """Build a unified timeline for a session by combining all data sources."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.session_parser = SessionMetadataParser(sessions_dir=sessions_dir)
        self.transcript_parser = TranscriptParser()
        self.tool_events_parser = ToolEventsParser()
        self.multi_agent_parser = MultiAgentParser()

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

        # Parse agent tree
        if viz.workspace:
            agent_tree = self.multi_agent_parser.parse_workspace(viz.workspace, session_id)
            viz.agent_tree = agent_tree

        # Sort timeline by start time
        viz.timeline.sort(key=lambda b: b.start_time)

        # Compute stats
        from .stats_builder import StatsBuilder
        viz.stats = StatsBuilder().build(viz.timeline)

        # Detect anomalies
        from .anomaly_builder import AnomalyBuilder
        viz.anomalies = AnomalyBuilder().build(viz)

        return viz

    def build_for_sessions(self, session_ids: list[str]) -> list[SessionVizData]:
        """Build viz data for multiple sessions."""
        results: list[SessionVizData] = []
        for sid in session_ids:
            viz = self.build(sid)
            if viz:
                results.append(viz)
        return results
